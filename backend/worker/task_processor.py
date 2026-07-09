"""Orchestrates one test_task's full lifecycle: load its context, execute
the underlying request, evaluate assertions, extract chain variables, and
decide whether it completed, needs a retry, or has failed permanently.

Deliberately does NOT write to Postgres itself -- it returns a TaskOutcome,
and the caller (the consume loop) is responsible for batching outcomes from
several tasks into one ResultWriter.write_batch() call. The one exception is
the Redis chain-context merge, which happens immediately, here, since a
chained task might need it before the batch gets written.
"""

from datetime import datetime, timezone
from uuid import UUID

from app.models.enums import TestTaskStatus
from app.queue.rate_limiter import RateLimiter
from app.queue.retry_queue import RetryQueue, compute_backoff_seconds
from app.queue.run_context import RunContext
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.assertion_repository import AssertionRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from worker.assertion_engine import evaluate_assertions
from worker.executor import Executor
from worker.result_writer import TaskOutcome
from worker.template_resolver import UndefinedVariableError, resolve_template
from worker.variable_extractor import ExtractionError, extract_variables

# How long to wait before retrying a task deferred by the rate limiter.
# Deliberately short and fixed, not exponential-backoff-based like a real
# execution failure -- an empty bucket refills on its own schedule, this
# isn't signaling that anything is wrong.
RATE_LIMITED_RETRY_DELAY_SECONDS = 1.0


class TaskProcessingError(Exception):
    """Raised when a task can't be processed at all -- e.g. its underlying
    test_task or api_request row is missing. Distinct from a normal
    execution failure (bad HTTP response, failed assertion), which produces
    a TaskOutcome rather than raising."""


class RateLimitedError(Exception):
    """Raised when the target host's token bucket has no tokens available.
    Deliberately does not consume a retry attempt -- being throttled by our
    own platform isn't a failure of the target API under test, and shouldn't
    eat into the caller's configured max_retries. The task is rescheduled
    via the same retry:pending -> RetrySweeper path a real failure uses, just
    without touching retry_count, and this task's process_task() call never
    reaches Executor.execute() at all."""


class TaskProcessor:
    def __init__(
        self,
        test_task_repository: TestTaskRepository,
        test_run_repository: TestRunRepository,
        api_request_repository: ApiRequestRepository,
        assertion_repository: AssertionRepository,
        executor: Executor,
        run_context: RunContext,
        retry_queue: RetryQueue,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.test_task_repository = test_task_repository
        self.test_run_repository = test_run_repository
        self.api_request_repository = api_request_repository
        self.assertion_repository = assertion_repository
        self.executor = executor
        self.run_context = run_context
        self.retry_queue = retry_queue
        self.rate_limiter = rate_limiter

    async def process_task(self, test_task_id: UUID, worker_id: UUID) -> TaskOutcome:
        test_task = await self.test_task_repository.get_by_id(test_task_id)
        if test_task is None:
            raise TaskProcessingError(f"test_task {test_task_id} does not exist.")

        api_request = await self.api_request_repository.get_by_id(test_task.api_request_id)
        if api_request is None:
            raise TaskProcessingError(
                f"test_task {test_task_id} references api_request "
                f"{test_task.api_request_id}, which does not exist."
            )

        test_run = await self.test_run_repository.get_by_id(test_task.test_run_id)
        if test_run is None:
            raise TaskProcessingError(
                f"test_task {test_task_id} references test_run {test_task.test_run_id}, "
                f"which does not exist."
            )

        environment_variables = (test_run.config or {}).get("environment_variables", {})
        chain_context = await self.run_context.get_all(test_run.id, test_task.data_row_index)
        if test_task.data_context:
            # CSV data-driven values are specific to this exact task instance
            # -- more specific than anything shared across the run/row, so
            # they win over both chain context and environment variables.
            chain_context = {**chain_context, **test_task.data_context}

        if self.rate_limiter is not None:
            await self._check_rate_limit(test_task, api_request, chain_context, environment_variables)

        result = await self.executor.execute(
            method=api_request.method,
            url=api_request.url,
            headers=api_request.headers,
            query_params=api_request.query_params,
            body=api_request.body,
            timeout_ms=api_request.timeout_ms,
            chain_context=chain_context,
            environment_variables=environment_variables,
        )

        assertions_passed: bool | None = None
        extracted_variables: dict[str, str] = {}
        failure_reasons: list[str] = []

        if not result.succeeded:
            failure_reasons.append(result.error_message or "Request failed with no error detail.")
        else:
            assertions = await self.assertion_repository.list_by_request(api_request.id)
            outcomes = evaluate_assertions(assertions, result)
            assertions_passed = all(o.passed for o in outcomes) if outcomes else True
            if not assertions_passed:
                failed_details = [o.detail for o in outcomes if not o.passed]
                failure_reasons.append(
                    f"{len(failed_details)} assertion(s) failed: {'; '.join(failed_details)}"
                )

            try:
                extracted_variables = extract_variables(api_request.extract_rules, result, chain_context)
            except ExtractionError as exc:
                failure_reasons.append(f"Variable extraction failed: {exc}")

        succeeded = not failure_reasons
        attempt_number = test_task.retry_count + 1

        if succeeded:
            if extracted_variables:
                await self.run_context.merge(test_run.id, extracted_variables, test_task.data_row_index)
            new_status = TestTaskStatus.COMPLETED
            new_retry_count = test_task.retry_count
            next_retry_at = None
        else:
            new_retry_count = attempt_number
            if new_retry_count <= test_task.max_retries:
                new_status = TestTaskStatus.RETRYING
                delay_seconds = compute_backoff_seconds(test_task.retry_count)
                next_attempt_unix = datetime.now(timezone.utc).timestamp() + delay_seconds
                await self.retry_queue.schedule_retry(test_task.id, next_attempt_unix)
                next_retry_at = datetime.fromtimestamp(next_attempt_unix, tz=timezone.utc)
            else:
                new_status = TestTaskStatus.FAILED
                next_retry_at = None

        return TaskOutcome(
            test_task_id=test_task.id,
            test_run_id=test_run.id,
            attempt_number=attempt_number,
            new_status=new_status,
            status_code=result.status_code,
            latency_ms=result.latency_ms,
            response_headers=result.response_headers,
            response_body=result.response_body,
            assertions_passed=assertions_passed,
            error_message="; ".join(failure_reasons) if failure_reasons else None,
            executed_by_worker_id=worker_id,
            retry_count=new_retry_count,
            next_retry_at=next_retry_at,
        )

    async def _check_rate_limit(
        self,
        test_task,
        api_request,
        chain_context: dict[str, str],
        environment_variables: dict[str, str],
    ) -> None:
        """Resolves the same URL template Executor.execute() is about to
        resolve again, purely to determine the real target host -- the raw,
        unresolved api_request.url can't be used directly since the host
        itself may be templated (e.g. "{{base_url}}/users"). resolve_template
        is pure and cheap; calling it twice costs nothing worth avoiding and
        keeps Executor's interface untouched."""
        try:
            resolved_url = resolve_template(api_request.url, chain_context, environment_variables)
        except UndefinedVariableError:
            # Let Executor.execute() hit and report the exact same error the
            # normal way -- nothing to rate-limit against if we can't even
            # tell what host this request is for.
            return

        host = RateLimiter.host_for_url(resolved_url)
        if host is None:
            return

        allowed = await self.rate_limiter.try_acquire(host)
        if not allowed:
            next_attempt_unix = (
                datetime.now(timezone.utc).timestamp() + RATE_LIMITED_RETRY_DELAY_SECONDS
            )
            await self.retry_queue.schedule_retry(test_task.id, next_attempt_unix)
            raise RateLimitedError(
                f"Rate limit exceeded for host {host!r}; task {test_task.id} rescheduled in "
                f"{RATE_LIMITED_RETRY_DELAY_SECONDS}s without consuming a retry attempt."
            )