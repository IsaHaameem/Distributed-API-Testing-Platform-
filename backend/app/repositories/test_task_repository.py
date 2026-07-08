"""Test task data-access layer."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TestTaskStatus
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

    async def list_by_run(
        self,
        test_run_id: UUID,
        *,
        status: TestTaskStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[TestTask], int]:
        """Return one page of tasks for a run, plus the total count matching
        the filter -- independent of page size, for pagination metadata."""
        base_query = select(TestTask).where(TestTask.test_run_id == test_run_id)
        if status is not None:
            base_query = base_query.where(TestTask.status == status)

        count_result = await self.session.execute(select(func.count()).select_from(base_query.subquery()))
        total = count_result.scalar_one()

        page_query = (
            base_query.order_by(TestTask.data_row_index, TestTask.sequence_order).limit(limit).offset(offset)
        )
        result = await self.session.execute(page_query)
        return list(result.scalars().all()), total