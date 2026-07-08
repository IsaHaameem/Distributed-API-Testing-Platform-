"""Worker and worker-heartbeat data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.worker import Worker
from app.models.worker_heartbeat import WorkerHeartbeat


class WorkerRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, worker_id: UUID) -> Worker | None:
        result = await self.session.execute(select(Worker).where(Worker.id == worker_id))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[Worker]:
        result = await self.session.execute(select(Worker).order_by(Worker.registered_at))
        return list(result.scalars().all())

    async def create(self, *, hostname: str, pid: int, capacity: int) -> Worker:
        worker = Worker(hostname=hostname, pid=pid, capacity=capacity)
        self.session.add(worker)
        await self.session.flush()
        await self.session.refresh(worker)
        return worker

    async def update(self, worker: Worker, **fields) -> Worker:
        for field_name, value in fields.items():
            setattr(worker, field_name, value)
        await self.session.flush()
        await self.session.refresh(worker)
        return worker

    async def record_heartbeat(
        self,
        *,
        worker_id: UUID,
        active_tasks_count: int,
        cpu_usage: float | None,
        memory_usage: float | None,
    ) -> WorkerHeartbeat:
        heartbeat = WorkerHeartbeat(
            worker_id=worker_id,
            active_tasks_count=active_tasks_count,
            cpu_usage=cpu_usage,
            memory_usage=memory_usage,
        )
        self.session.add(heartbeat)
        await self.session.flush()
        await self.session.refresh(heartbeat)
        return heartbeat