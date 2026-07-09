"""Schedule data-access layer."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.schedule import Schedule


class ScheduleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, schedule_id: UUID) -> Schedule | None:
        result = await self.session.execute(select(Schedule).where(Schedule.id == schedule_id))
        return result.scalar_one_or_none()

    async def list_by_collection(self, collection_id: UUID) -> list[Schedule]:
        result = await self.session.execute(
            select(Schedule)
            .where(Schedule.collection_id == collection_id)
            .order_by(Schedule.created_at)
        )
        return list(result.scalars().all())

    async def list_due(self, now: datetime, limit: int = 50) -> list[Schedule]:
        """Every active schedule whose next_run_at has passed, earliest
        first. Used by CronScheduler to find what needs triggering this sweep."""
        result = await self.session.execute(
            select(Schedule)
            .where(Schedule.is_active.is_(True))
            .where(Schedule.next_run_at.is_not(None))
            .where(Schedule.next_run_at <= now)
            .order_by(Schedule.next_run_at)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create(self, *, collection_id: UUID, created_by: UUID, **fields) -> Schedule:
        schedule = Schedule(collection_id=collection_id, created_by=created_by, **fields)
        self.session.add(schedule)
        await self.session.flush()
        await self.session.refresh(schedule)
        return schedule

    async def update(self, schedule: Schedule, **fields) -> Schedule:
        for field_name, value in fields.items():
            setattr(schedule, field_name, value)
        await self.session.flush()
        await self.session.refresh(schedule)
        return schedule

    async def delete(self, schedule: Schedule) -> None:
        await self.session.delete(schedule)
        await self.session.flush()