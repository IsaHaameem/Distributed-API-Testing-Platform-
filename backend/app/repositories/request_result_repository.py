"""Request result data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_request import ApiRequest
from app.models.request_result import RequestResult
from app.models.test_task import TestTask


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
            latest_by_task[row.test_task_id] = row
        return latest_by_task

    async def list_by_task_id(self, test_task_id: UUID) -> list[RequestResult]:
        """Every attempt of one task, oldest first -- the full retry history,
        including the response headers/body snippet fields get_latest_by_task_ids
        deliberately omits (that method backs a list view; this backs a detail
        view, where the whole point is showing what get_latest_by_task_ids
        doesn't)."""
        result = await self.session.execute(
            select(RequestResult)
            .where(RequestResult.test_task_id == test_task_id)
            .order_by(RequestResult.attempt_number)
        )
        return list(result.scalars().all())

    async def list_by_run(self, test_run_id: UUID) -> list[tuple[RequestResult, TestTask, ApiRequest]]:
        """Every attempt of every task in a run, joined with enough task/
        request context to be self-contained -- the data source for results
        export. Unlike get_latest_by_task_ids, this deliberately returns
        every attempt, not just the latest one."""
        result = await self.session.execute(
            select(RequestResult, TestTask, ApiRequest)
            .join(TestTask, TestTask.id == RequestResult.test_task_id)
            .join(ApiRequest, ApiRequest.id == TestTask.api_request_id)
            .where(TestTask.test_run_id == test_run_id)
            .order_by(TestTask.data_row_index, TestTask.sequence_order, RequestResult.attempt_number)
        )
        return [(row[0], row[1], row[2]) for row in result.all()]