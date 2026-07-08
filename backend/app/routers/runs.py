"""Test run endpoints -- the entry point that actually feeds the Redis
Streams queue built in Steps 9-10. GET /runs/{id}, listing, and results
export are Part 2/3 -- this is creation only.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_redis
from app.models.test_run import TestRun
from app.models.user import User
from app.queue.constants import TASK_STREAM_NAME, WORKER_CONSUMER_GROUP
from app.queue.stream_client import StreamQueue
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from app.schemas.test_run import TestRunCreate, TestRunRead
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
    )


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