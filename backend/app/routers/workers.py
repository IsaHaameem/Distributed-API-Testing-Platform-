"""Read-only worker observability endpoint.

There is deliberately no POST /workers/register or /workers/{id}/heartbeat
here. Those aren't user-facing operations -- the worker process (a future
milestone) shares this same codebase and calls WorkerService directly as
Python, rather than round-tripping through its own backend's HTTP API to
announce itself. This endpoint exists purely so a human, or a future
dashboard, can see what's actually running.
"""

from fastapi import APIRouter, Depends
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db, get_redis
from app.models.user import User
from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository
from app.schemas.worker import WorkerRead
from app.services.worker_service import WorkerService

router = APIRouter(tags=["workers"])


def get_worker_service(
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> WorkerService:
    return WorkerService(WorkerRepository(db), WorkerRegistry(redis_client))


@router.get("/workers", response_model=list[WorkerRead])
async def list_workers(
    current_user: User = Depends(get_current_user),
    service: WorkerService = Depends(get_worker_service),
) -> list[WorkerRead]:
    entries = await service.list_workers()
    return [
        WorkerRead(
            id=entry["worker"].id,
            hostname=entry["worker"].hostname,
            pid=entry["worker"].pid,
            status=entry["worker"].status,
            capacity=entry["worker"].capacity,
            registered_at=entry["worker"].registered_at,
            last_seen_at=entry["worker"].last_seen_at,
            is_alive=entry["is_alive"],
        )
        for entry in entries
    ]