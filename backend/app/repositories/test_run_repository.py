"""Test run data-access layer.

Minimal by design, same reasoning as TestTaskRepository -- task_processor
only needs to read a run's config (for resolved environment variables) and
id (for the chain-context key). Full CRUD belongs to run-orchestration.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.test_run import TestRun


class TestRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, test_run_id: UUID) -> TestRun | None:
        result = await self.session.execute(select(TestRun).where(TestRun.id == test_run_id))
        return result.scalar_one_or_none()