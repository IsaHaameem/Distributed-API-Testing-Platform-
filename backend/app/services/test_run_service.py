"""Test run orchestration: resolves a collection's requests and a project's
environment variables, builds one test_task per (request, data row) pair,
and enqueues them onto the Redis Streams queue for workers to pick up.

This is the one place in the whole codebase where API-layer code and the
Step 9/10 queue infrastructure meet -- everything before this milestone
built the machinery; this is what actually feeds it.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import CollectionHasNoRequestsError, CollectionNotFoundError
from app.models.enums import TestRunStatus, TestRunType
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.queue.stream_client import StreamQueue
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
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
    ) -> None:
        self.test_run_repository = test_run_repository
        self.test_task_repository = test_task_repository
        self.api_request_repository = api_request_repository
        self.environment_variable_repository = environment_variable_repository
        self.collection_repository = collection_repository
        self.project_repository = project_repository
        self.member_repository = member_repository
        self.stream_queue = stream_queue

    async def create_run(
        self, *, current_user: User, collection_id: UUID, data_rows: list[dict[str, str]] | None
    ) -> TestRun:
        organization_id = await organization_id_for_collection(
            self.collection_repository, self.project_repository, collection_id, CollectionNotFoundError
        )
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )

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
            initiated_by=current_user.id,
            status=TestRunStatus.RUNNING,
            run_type=TestRunType.MANUAL,
            total_tasks=total_tasks,
            config={"environment_variables": environment_variables},
            started_at=datetime.now(timezone.utc),
        )

        # Row-major: every request for row 0, in order, before any request
        # for row 1 -- so a chain within one data iteration completes before
        # the next iteration starts, matching how RunContext now scopes
        # extracted variables per row.
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