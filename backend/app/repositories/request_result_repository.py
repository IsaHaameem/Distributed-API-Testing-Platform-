"""Request result data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.request_result import RequestResult


class RequestResultRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_latest_by_task_ids(self, test_task_ids: list[UUID]) -> dict[UUID, RequestResult]:
        """Return the most recent attempt's result for each given task id.
        Tasks with no attempts yet (still pending) simply aren't in the
        returned dict -- callers should treat a missing key as "no result yet."
        """
        if not test_task_ids:
            return {}

        result = await self.session.execute(
            select(RequestResult)
            .where(RequestResult.test_task_id.in_(test_task_ids))
            .order_by(RequestResult.test_task_id, RequestResult.attempt_number)
        )

        latest_by_task: dict[UUID, RequestResult] = {}
        for row in result.scalars().all():
            # Ascending attempt_number means each later row for the same task
            # overwrites the previous one in the dict, leaving the highest
            # attempt_number -- the most recent attempt -- once the loop ends.
            latest_by_task[row.test_task_id] = row
        return latest_by_task