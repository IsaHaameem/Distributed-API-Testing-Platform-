"""Test task data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_task import TestTask


class TestTaskRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, test_task_id: UUID) -> TestTask | None:
        result = await self.session.execute(select(TestTask).where(TestTask.id == test_task_id))
        return result.scalar_one_or_none()

    async def bulk_create(self, tasks: list[TestTask]) -> list[TestTask]:
        """Insert every task in one flush. Each task's id is already
        populated on return -- UUIDv7 generation is a Python-side default
        (app.core.identifiers.generate_uuid7), so it's assigned when the
        INSERT is compiled, not read back from the database afterward."""
        self.session.add_all(tasks)
        await self.session.flush()
        return tasks