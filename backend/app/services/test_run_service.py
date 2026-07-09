"""Test run orchestration: resolves a collection's requests and a project's
environment variables, builds one test_task per (request, data row) pair,
and enqueues them onto the Redis Streams queue for workers to pick up.

create_run is the HTTP-facing path, requiring the caller to be an
organization member. create_scheduled_run is the cron scheduler's path --
no HTTP request or membership re-check behind it; the schedule's own
existence and is_active flag (already admin/owner-gated at creation/update
time, per ScheduleService) are the authorization here, not a per-trigger
re-validation of the creator's current membership.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import (
    CollectionHasNoRequestsError,
    CollectionNotFoundError,
    TestRunNotFoundError,
    TestTaskNotFoundError,
)
from app.models.enums import TestRunStatus, TestRunType, TestTaskStatus
from app.models.execution_log import ExecutionLog
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.queue.stream_client import StreamQueue
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.execution_log_repository import ExecutionLogRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.request_result_repository import RequestResultRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from app.schemas.test_task import ResultExportRow
from app.services.authorization import organization_id_for_collection, require_membership


class TestRunService:
    def __init__(
        self,
        test_run_repository: TestRunRepository,
        test_task_repository: TestTaskRepository,
        api_request_repository: ApiRequestRepository,
        environment_variable_repository: EnvironmentVariableRepository,
        collection_repository: CollectionRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
        stream_queue: StreamQueue,
        request_result_repository: RequestResultRepository,
        execution_log_repository: ExecutionLogRepository,
    ) -> None:
        self.test_run_repository = test_run_repository
        self.test_task_repository = test_task_repository
        self.api_request_repository = api_request_repository
        self.environment_variable_repository = environment_variable_repository
        self.collection_repository = collection_repository
        self.project_repository = project_repository
        self.member_repository = member_repository
        self.stream_queue = stream_queue
        self.request_result_repository = request_result_repository
        self.execution_log_repository = execution_log_repository

    async def create_run(
        self, *, current_user: User, collection_id: UUID, data_rows: list[dict[str, str]] | None
    ) -> TestRun:
        """HTTP-facing: requires current_user to be a member of the
        collection's organization."""
        organization_id = await organization_id_for_collection(
            self.collection_repository, self.project_repository, collection_id, CollectionNotFoundError
        )
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )
        return await self._create_run(
            collection_id=collection_id,
            initiated_by=current_user.id,
            run_type=TestRunType.MANUAL,
            data_rows=data_rows,
        )

    async def create_scheduled_run(self, *, collection_id: UUID, initiated_by: UUID) -> TestRun:
        """Triggered by the cron scheduler -- no HTTP request, no membership
        re-check. See the module docstring for why."""
        return await self._create_run(
            collection_id=collection_id,
            initiated_by=initiated_by,
            run_type=TestRunType.SCHEDULED,
            data_rows=None,
        )

    async def _create_run(
        self,
        *,
        collection_id: UUID,
        initiated_by: UUID,
        run_type: TestRunType,
        data_rows: list[dict[str, str]] | None,
    ) -> TestRun:
        api_requests = await self.api_request_repository.list_by_collection(collection_id)
        if not api_requests:
            raise CollectionHasNoRequestsError()

        collection = await self.collection_repository.get_by_id(collection_id)
        environment_variables = {
            v.key: v.value
            for v in await self.environment_variable_repository.list_by_project(collection.project_id)
        }

        rows: list[dict[str, str] | None] = data_rows if data_rows else [None]
        total_tasks = len(api_requests) * len(rows)

        test_run = await self.test_run_repository.create(
            collection_id=collection_id,
            initiated_by=initiated_by,
            status=TestRunStatus.RUNNING,
            run_type=run_type,
            total_tasks=total_tasks,
            config={"environment_variables": environment_variables},
            started_at=datetime.now(timezone.utc),
        )

        pending_tasks = [
            TestTask(
                test_run_id=test_run.id,
                api_request_id=api_request.id,
                sequence_order=api_request.order_index,
                data_row_index=row_index if data_rows else None,
                data_context=row,
            )
            for row_index, row in enumerate(rows)
            for api_request in api_requests
        ]
        created_tasks = await self.test_task_repository.bulk_create(pending_tasks)

        await self.stream_queue.ensure_group()
        for task in created_tasks:
            await self.stream_queue.enqueue(task.id)

        return test_run

    async def list_runs(
        self, *, current_user: User, collection_id: UUID, status: TestRunStatus | None
    ) -> list[TestRun]:
        organization_id = await organization_id_for_collection(
            self.collection_repository, self.project_repository, collection_id, CollectionNotFoundError
        )
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )
        return await self.test_run_repository.list_by_collection(collection_id, status=status)

    async def get_run(self, *, current_user: User, test_run_id: UUID) -> TestRun:
        return await self._get_authorized_run(current_user, test_run_id)

    async def list_tasks(
        self,
        *,
        current_user: User,
        test_run_id: UUID,
        status: TestTaskStatus | None,
        limit: int,
        offset: int,
    ) -> tuple[list[TestTask], dict[UUID, RequestResult], int]:
        await self._get_authorized_run(current_user, test_run_id)
        tasks, total = await self.test_task_repository.list_by_run(
            test_run_id, status=status, limit=limit, offset=offset
        )
        latest_results = await self.request_result_repository.get_latest_by_task_ids(
            [task.id for task in tasks]
        )
        return tasks, latest_results, total

    async def get_task_detail(
        self, *, current_user: User, test_run_id: UUID, test_task_id: UUID
    ) -> tuple[TestTask, list[RequestResult], list[ExecutionLog]]:
        """Full detail for one task: every attempt (not just the latest) and
        every execution log line. Authorization is run-scoped, same as every
        other run-nested endpoint; a task that exists but belongs to a
        *different* run 404s the same way a nonexistent one would -- the URL
        claims a task lives under this run, and if it doesn't, that's not
        confirmed to the caller either way."""
        await self._get_authorized_run(current_user, test_run_id)

        test_task = await self.test_task_repository.get_by_id(test_task_id)
        if test_task is None or test_task.test_run_id != test_run_id:
            raise TestTaskNotFoundError()

        attempts = await self.request_result_repository.list_by_task_id(test_task_id)
        logs = await self.execution_log_repository.list_by_task(test_task_id)
        return test_task, attempts, logs

    async def export_results(self, *, current_user: User, test_run_id: UUID) -> list[ResultExportRow]:
        await self._get_authorized_run(current_user, test_run_id)
        rows = await self.request_result_repository.list_by_run(test_run_id)
        return [
            ResultExportRow(
                test_task_id=task.id,
                api_request_name=api_request.name,
                method=api_request.method.value,
                url=api_request.url,
                data_row_index=task.data_row_index,
                attempt_number=result.attempt_number,
                status_code=result.status_code,
                latency_ms=result.latency_ms,
                assertions_passed=result.assertions_passed,
                error_message=result.error_message,
                executed_at=result.executed_at,
            )
            for result, task, api_request in rows
        ]

    async def _get_authorized_run(self, current_user: User, test_run_id: UUID) -> TestRun:
        test_run = await self.test_run_repository.get_by_id(test_run_id)
        if test_run is None:
            raise TestRunNotFoundError()

        organization_id = await organization_id_for_collection(
            self.collection_repository,
            self.project_repository,
            test_run.collection_id,
            TestRunNotFoundError,
        )
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=TestRunNotFoundError,
        )
        return test_run