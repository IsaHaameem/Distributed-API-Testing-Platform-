"""Worker registration and heartbeat orchestration.

Composes the durable Postgres record (WorkerRepository) with the live Redis
liveness signal (WorkerRegistry) -- registering or heartbeating always
touches both, so there's no path where the DB thinks a worker is online
after Redis has already expired it, or vice versa.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.core.exceptions import WorkerNotFoundError
from app.models.enums import WorkerStatus
from app.models.worker import Worker
from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository


class WorkerService:
    def __init__(self, worker_repository: WorkerRepository, worker_registry: WorkerRegistry) -> None:
        self.worker_repository = worker_repository
        self.worker_registry = worker_registry

    async def register(self, *, hostname: str, pid: int, capacity: int) -> Worker:
        worker = await self.worker_repository.create(hostname=hostname, pid=pid, capacity=capacity)
        await self.worker_registry.mark_alive(worker.id)
        return worker

    async def heartbeat(
        self,
        *,
        worker_id: UUID,
        active_tasks_count: int,
        cpu_usage: float | None = None,
        memory_usage: float | None = None,
    ) -> Worker:
        worker = await self.worker_repository.get_by_id(worker_id)
        if worker is None:
            raise WorkerNotFoundError()

        await self.worker_registry.mark_alive(worker_id)
        await self.worker_repository.record_heartbeat(
            worker_id=worker_id,
            active_tasks_count=active_tasks_count,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
        )
        return await self.worker_repository.update(worker, last_seen_at=datetime.now(timezone.utc))

    async def deregister(self, *, worker_id: UUID) -> None:
        worker = await self.worker_repository.get_by_id(worker_id)
        if worker is None:
            raise WorkerNotFoundError()
        await self.worker_registry.deregister(worker_id)
        await self.worker_repository.update(worker, status=WorkerStatus.OFFLINE)

    async def list_workers(self) -> list[dict]:
        """Every registered worker, each annotated with LIVE Redis status --
        which may disagree with the DB's `status` column if a process died
        without deregistering. That disagreement is itself the useful signal."""
        workers = await self.worker_repository.list_all()
        result = []
        for worker in workers:
            alive = await self.worker_registry.is_alive(worker.id)
            result.append({"worker": worker, "is_alive": alive})
        return result