"""Test run endpoints -- creation (which feeds the Redis Streams queue),
reading run status, listing a collection's runs, listing a run's tasks with
their latest execution result, and exporting full results. Cancellation is
explicitly not here -- see the milestone notes on why.
"""

import csv
import io
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import JSONResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_redis
from app.models.enums import TestRunStatus, TestTaskStatus
from app.models.execution_log import ExecutionLog
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.queue.constants import TASK_STREAM_NAME, WORKER_CONSUMER_GROUP
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
from app.schemas.test_run import TestRunCreate, TestRunRead
from app.schemas.test_task import (
    AttemptRead,
    ExecutionLogRead,
    LatestResultRead,
    ResultExportRow,
    TestTaskDetailRead,
    TestTaskListRead,
    TestTaskRead,
)
from app.services.test_run_service import TestRunService

router = APIRouter(tags=["runs"])


def get_task_stream_queue(redis_client: Redis = Depends(get_redis)) -> StreamQueue:
    """Its own dependency, separate from get_test_run_service, specifically
    so tests can override just this piece -- pointing run creation at an
    isolated, per-test stream instead of the real one a running worker
    container consumes from -- without reconstructing the service's entire
    dependency tree to do it."""
    return StreamQueue(redis_client, TASK_STREAM_NAME, WORKER_CONSUMER_GROUP)


def get_test_run_service(
    db: AsyncSession = Depends(get_db),
    stream_queue: StreamQueue = Depends(get_task_stream_queue),
) -> TestRunService:
    return TestRunService(
        TestRunRepository(db),
        TestTaskRepository(db),
        ApiRequestRepository(db),
        EnvironmentVariableRepository(db),
        CollectionRepository(db),
        ProjectRepository(db),
        OrganizationMemberRepository(db),
        stream_queue,
        RequestResultRepository(db),
        ExecutionLogRepository(db),
    )


def _task_to_read(task, latest_result) -> TestTaskRead:
    return TestTaskRead(
        id=task.id,
        test_run_id=task.test_run_id,
        api_request_id=task.api_request_id,
        sequence_order=task.sequence_order,
        data_row_index=task.data_row_index,
        status=task.status,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        next_retry_at=task.next_retry_at,
        latest_result=(
            LatestResultRead(
                status_code=latest_result.status_code,
                latency_ms=latest_result.latency_ms,
                assertions_passed=latest_result.assertions_passed,
                error_message=latest_result.error_message,
                executed_at=latest_result.executed_at,
            )
            if latest_result is not None
            else None
        ),
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _task_detail_to_read(
    task: TestTask, attempts: list[RequestResult], logs: list[ExecutionLog]
) -> TestTaskDetailRead:
    return TestTaskDetailRead(
        id=task.id,
        test_run_id=task.test_run_id,
        api_request_id=task.api_request_id,
        sequence_order=task.sequence_order,
        data_row_index=task.data_row_index,
        status=task.status,
        retry_count=task.retry_count,
        max_retries=task.max_retries,
        next_retry_at=task.next_retry_at,
        attempts=[
            AttemptRead(
                attempt_number=a.attempt_number,
                status_code=a.status_code,
                latency_ms=a.latency_ms,
                response_headers=a.response_headers,
                response_body_snippet=a.response_body_snippet,
                assertions_passed=a.assertions_passed,
                error_message=a.error_message,
                executed_by_worker_id=a.executed_by_worker_id,
                executed_at=a.executed_at,
            )
            for a in attempts
        ],
        logs=[
            ExecutionLogRead(level=log.level, message=log.message, created_at=log.created_at)
            for log in logs
        ],
        created_at=task.created_at,
        updated_at=task.updated_at,
    )


def _rows_to_csv(rows: list[ResultExportRow]) -> str:
    fieldnames = list(ResultExportRow.model_fields.keys())
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(row.model_dump(mode="json"))
    return buffer.getvalue()


@router.post(
    "/collections/{collection_id}/runs",
    response_model=TestRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_run(
    collection_id: UUID,
    payload: TestRunCreate,
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> TestRun:
    return await service.create_run(
        current_user=current_user, collection_id=collection_id, data_rows=payload.data_rows
    )


@router.get("/collections/{collection_id}/runs", response_model=list[TestRunRead])
async def list_runs(
    collection_id: UUID,
    status_filter: TestRunStatus | None = Query(default=None, alias="status"),
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> list[TestRun]:
    return await service.list_runs(
        current_user=current_user, collection_id=collection_id, status=status_filter
    )


@router.get("/runs/{run_id}", response_model=TestRunRead)
async def get_run(
    run_id: UUID,
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> TestRun:
    return await service.get_run(current_user=current_user, test_run_id=run_id)


@router.get("/runs/{run_id}/tasks", response_model=TestTaskListRead)
async def list_run_tasks(
    run_id: UUID,
    status_filter: TestTaskStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> TestTaskListRead:
    tasks, latest_results, total = await service.list_tasks(
        current_user=current_user,
        test_run_id=run_id,
        status=status_filter,
        limit=limit,
        offset=offset,
    )
    return TestTaskListRead(
        tasks=[_task_to_read(task, latest_results.get(task.id)) for task in tasks],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/runs/{run_id}/tasks/{task_id}", response_model=TestTaskDetailRead)
async def get_task_detail(
    run_id: UUID,
    task_id: UUID,
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> TestTaskDetailRead:
    task, attempts, logs = await service.get_task_detail(
        current_user=current_user, test_run_id=run_id, test_task_id=task_id
    )
    return _task_detail_to_read(task, attempts, logs)


@router.get("/runs/{run_id}/results/export")
async def export_run_results(
    run_id: UUID,
    export_format: Literal["csv", "json"] = Query(default="json", alias="format"),
    current_user: User = Depends(get_current_user),
    service: TestRunService = Depends(get_test_run_service),
) -> Response:
    rows = await service.export_results(current_user=current_user, test_run_id=run_id)

    if export_format == "csv":
        return Response(
            content=_rows_to_csv(rows),
            media_type="text/csv",
            headers={"Content-Disposition": f'attachment; filename="run-{run_id}-results.csv"'},
        )

    return JSONResponse(
        content=[row.model_dump(mode="json") for row in rows],
        headers={"Content-Disposition": f'attachment; filename="run-{run_id}-results.json"'},
    )