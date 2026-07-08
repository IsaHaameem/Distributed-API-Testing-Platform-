"""Test run data-access layer."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import TestRunStatus, TestRunType
from app.models.test_run import TestRun


class TestRunRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, test_run_id: UUID) -> TestRun | None:
        result = await self.session.execute(select(TestRun).where(TestRun.id == test_run_id))
        return result.scalar_one_or_none()

    async def list_by_collection(
        self, collection_id: UUID, status: TestRunStatus | None = None
    ) -> list[TestRun]:
        query = select(TestRun).where(TestRun.collection_id == collection_id)
        if status is not None:
            query = query.where(TestRun.status == status)
        query = query.order_by(TestRun.created_at.desc())
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def create(
        self,
        *,
        collection_id: UUID,
        initiated_by: UUID,
        status: TestRunStatus,
        run_type: TestRunType,
        total_tasks: int,
        config: dict,
        started_at: datetime,
    ) -> TestRun:
        test_run = TestRun(
            collection_id=collection_id,
            initiated_by=initiated_by,
            status=status,
            run_type=run_type,
            total_tasks=total_tasks,
            config=config,
            started_at=started_at,
        )
        self.session.add(test_run)
        await self.session.flush()
        await self.session.refresh(test_run)
        return test_run