"""Test task data-access layer.

Minimal by design -- this only has what task_processor actually needs
(reading a single task by id). Full CRUD for test_tasks belongs to the
run-orchestration milestone that creates them in the first place.
"""

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