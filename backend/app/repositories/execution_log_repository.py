"""Execution log data-access layer.

ResultWriter has written a row here on every task outcome since Step 10, but
nothing ever read them back until this repository -- execution_logs was a
fully write-only table. Deliberately minimal, matching TestTaskRepository/
TestRunRepository's own precedent: one method, because task detail is the
only caller so far.
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.execution_log import ExecutionLog


class ExecutionLogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_task(self, test_task_id: UUID) -> list[ExecutionLog]:
        """Every log line for one task, oldest first."""
        result = await self.session.execute(
            select(ExecutionLog)
            .where(ExecutionLog.test_task_id == test_task_id)
            .order_by(ExecutionLog.created_at)
        )
        return list(result.scalars().all())
