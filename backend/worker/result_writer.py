"""Batched Postgres writer for completed task executions.

Workers naturally batch by processing N tasks per stream-consume cycle
(bounded by the batch size passed to StreamQueue.consume) and writing all N
outcomes in one write_batch() call, rather than one write per task. This is
what actually determines whether the platform hits its throughput targets --
the HTTP layer can trivially exceed 1,500 req/s with asyncio; Postgres write
volume is the real constraint, per the Step 1 design notes.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import LogLevel, TestRunStatus, TestTaskStatus
from app.models.execution_log import ExecutionLog
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask

RESPONSE_BODY_SNIPPET_MAX_CHARS = 4096


@dataclass
class TaskOutcome:
    test_task_id: UUID
    test_run_id: UUID
    attempt_number: int
    new_status: TestTaskStatus
    status_code: int | None
    latency_ms: int
    response_headers: dict | None
    response_body: str | None
    assertions_passed: bool | None
    error_message: str | None
    executed_by_worker_id: UUID
    retry_count: int
    next_retry_at: datetime | None


class ResultWriter:
    async def write_batch(self, outcomes: list[TaskOutcome], session: AsyncSession) -> None:
        """Persist an entire batch of task outcomes in as few round-trips as
        reasonably achievable: one INSERT for all request_results, one for
        all execution_logs, one bulk UPDATE for all test_tasks, and one
        UPDATE per distinct test_run represented in the batch -- then a
        single commit for the whole batch."""
        if not outcomes:
            return

        session.add_all(self._build_request_result(o) for o in outcomes)
        session.add_all(self._build_log(o) for o in outcomes)

        # Bare update(TestTask), no .where() -- SQLAlchemy generates the
        # primary-key WHERE clause itself from each dict's "id". Adding an
        # explicit .where() here is a documented footgun that silently
        # matches nothing (WHERE id = 1 AND id = NULL) rather than erroring.
        await session.execute(
            update(TestTask),
            [
                {
                    "id": o.test_task_id,
                    "status": o.new_status,
                    "retry_count": o.retry_count,
                    "next_retry_at": o.next_retry_at,
                    "assigned_worker_id": o.executed_by_worker_id,
                }
                for o in outcomes
            ],
        )

        await self._update_run_progress(outcomes, session)
        await session.commit()

    async def _update_run_progress(self, outcomes: list[TaskOutcome], session: AsyncSession) -> None:
        deltas: dict[UUID, dict[str, int]] = {}
        for outcome in outcomes:
            if outcome.new_status not in (TestTaskStatus.COMPLETED, TestTaskStatus.FAILED):
                continue  # RETRYING tasks aren't done -- don't touch run counters for them
            delta = deltas.setdefault(outcome.test_run_id, {"completed": 0, "failed": 0})
            key = "completed" if outcome.new_status == TestTaskStatus.COMPLETED else "failed"
            delta[key] += 1

        for run_id, delta in deltas.items():
            # Column-expression increment (not read-then-write) so concurrent
            # workers updating the same run's counters can't race each other.
            await session.execute(
                update(TestRun)
                .where(TestRun.id == run_id)
                .values(
                    completed_tasks=TestRun.completed_tasks + delta["completed"],
                    failed_tasks=TestRun.failed_tasks + delta["failed"],
                )
            )

            result = await session.execute(select(TestRun).where(TestRun.id == run_id))
            test_run = result.scalar_one()
            is_now_finished = test_run.completed_tasks + test_run.failed_tasks >= test_run.total_tasks
            if is_now_finished and test_run.status == TestRunStatus.RUNNING:
                # Deliberately just COMPLETED regardless of how many individual
                # tasks failed -- completed_tasks/failed_tasks already carry
                # that detail. Whether a run with failures should ever be
                # marked FAILED overall is an orchestration semantics
                # question, not this module's to decide.
                test_run.status = TestRunStatus.COMPLETED
                test_run.completed_at = datetime.now(timezone.utc)

    def _build_request_result(self, outcome: TaskOutcome) -> RequestResult:
        snippet = outcome.response_body
        if snippet is not None and len(snippet) > RESPONSE_BODY_SNIPPET_MAX_CHARS:
            snippet = snippet[:RESPONSE_BODY_SNIPPET_MAX_CHARS]

        return RequestResult(
            test_task_id=outcome.test_task_id,
            attempt_number=outcome.attempt_number,
            status_code=outcome.status_code,
            latency_ms=outcome.latency_ms,
            response_headers=outcome.response_headers,
            response_body_snippet=snippet,
            assertions_passed=outcome.assertions_passed,
            error_message=outcome.error_message,
            executed_by_worker_id=outcome.executed_by_worker_id,
        )

    def _build_log(self, outcome: TaskOutcome) -> ExecutionLog:
        if outcome.new_status == TestTaskStatus.COMPLETED:
            level = LogLevel.INFO
            message = (
                f"Task completed (attempt {outcome.attempt_number}, status {outcome.status_code})."
            )
        elif outcome.new_status == TestTaskStatus.RETRYING:
            level = LogLevel.WARNING
            message = f"Attempt {outcome.attempt_number} failed, will retry: {outcome.error_message}"
        else:
            level = LogLevel.ERROR
            message = (
                f"Task failed permanently after {outcome.attempt_number} attempt(s): "
                f"{outcome.error_message}"
            )

        return ExecutionLog(
            test_run_id=outcome.test_run_id,
            test_task_id=outcome.test_task_id,
            level=level,
            message=message,
        )