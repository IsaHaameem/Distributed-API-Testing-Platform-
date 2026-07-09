"""Integration tests for TaskProcessor -- the module that composes the
executor, assertion engine, extractor, chain context, and retry scheduling
into "process one task correctly." Uses httpx.MockTransport for the HTTP
layer (no real network) and real Redis/Postgres for everything else.

_processor() gives every test its own isolated RetryQueue (unique Redis key)
by default -- the real backend container's lifespan now runs a live retry
sweeper (Step 12 Part 1) continuously, and a test writing to the real
retry:pending key would race it exactly the way test_run_orchestration.py
raced a real running worker on the real task stream.
"""

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.api_request import ApiRequest
from app.models.assertion import Assertion
from app.models.collection import Collection
from app.models.enums import (
    AssertionType,
    HttpMethod,
    OrganizationRole,
    TestRunStatus,
    TestRunType,
    TestTaskStatus,
)
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.queue.rate_limiter import RateLimiter
from app.queue.retry_queue import RETRY_ZSET_KEY, RetryQueue
from app.queue.run_context import RunContext
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.assertion_repository import AssertionRepository
from app.repositories.test_run_repository import TestRunRepository
from app.repositories.test_task_repository import TestTaskRepository
from worker.executor import Executor
from worker.task_processor import RateLimitedError, TaskProcessingError, TaskProcessor


async def _build_task(
    session: AsyncSession,
    *,
    url: str = "https://example.com/status",
    method: HttpMethod = HttpMethod.GET,
    extract_rules: list | None = None,
    assertion_configs: list[tuple[str, dict]] | None = None,
    environment_variables: dict | None = None,
    retry_count: int = 0,
    max_retries: int = 3,
    data_context: dict | None = None,
) -> tuple[TestTask, TestRun]:
    user = User(
        email=f"processor-test-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("a-strong-password-123"),
        full_name="Processor Test User",
    )
    session.add(user)
    await session.flush()

    org = Organization(name="Processor Test Org", slug=f"processor-test-{uuid.uuid4().hex[:12]}")
    session.add(org)
    await session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))

    project = Project(organization_id=org.id, name="Project", created_by=user.id)
    session.add(project)
    await session.flush()

    collection = Collection(project_id=project.id, name="Collection")
    session.add(collection)
    await session.flush()

    api_request = ApiRequest(
        collection_id=collection.id,
        name="Request",
        method=method,
        url=url,
        extract_rules=extract_rules or [],
    )
    session.add(api_request)
    await session.flush()

    for assertion_type, config in assertion_configs or []:
        session.add(
            Assertion(api_request_id=api_request.id, type=AssertionType(assertion_type), config=config)
        )
    await session.flush()

    test_run = TestRun(
        collection_id=collection.id,
        initiated_by=user.id,
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=1,
        config={"environment_variables": environment_variables or {}},
    )
    session.add(test_run)
    await session.flush()

    test_task = TestTask(
        test_run_id=test_run.id,
        api_request_id=api_request.id,
        retry_count=retry_count,
        max_retries=max_retries,
        data_context=data_context,
    )
    session.add(test_task)
    await session.flush()

    return test_task, test_run


def _processor(
    db_session: AsyncSession,
    redis_client: Redis,
    handler,
    retry_queue: RetryQueue | None = None,
    rate_limiter: RateLimiter | None = None,
) -> TaskProcessor:
    http_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TaskProcessor(
        TestTaskRepository(db_session),
        TestRunRepository(db_session),
        ApiRequestRepository(db_session),
        AssertionRepository(db_session),
        Executor(http_client),
        RunContext(redis_client),
        retry_queue or RetryQueue(redis_client, zset_key=f"test:retry:{uuid.uuid4().hex[:12]}"),
        rate_limiter,
    )


@pytest.mark.asyncio
async def test_process_task_completes_successfully_with_passing_assertions(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(
        db_session, assertion_configs=[("status_code_equals", {"expected": 200})]
    )
    processor = _processor(db_session, redis_client, handler)

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.new_status == TestTaskStatus.COMPLETED
    assert outcome.status_code == 200
    assert outcome.assertions_passed is True
    assert outcome.attempt_number == 1
    assert outcome.error_message is None


@pytest.mark.asyncio
async def test_process_task_extracts_and_merges_chain_variables(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"token": "abc123"})

    test_task, test_run = await _build_task(
        db_session,
        url="https://example.com/login",
        extract_rules=[{"type": "json_path", "path": "$.token", "save_as": "authToken"}],
    )
    processor = _processor(db_session, redis_client, handler)

    await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    run_context = RunContext(redis_client)
    context_after = await run_context.get_all(test_run.id)
    assert context_after == {"authToken": "abc123"}

    await redis_client.delete(run_context.context_key(test_run.id))


@pytest.mark.asyncio
async def test_process_task_uses_environment_variables_from_run_config(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200)

    test_task, test_run = await _build_task(
        db_session, url="{{baseUrl}}/users", environment_variables={"baseUrl": "https://api.example.com"}
    )
    processor = _processor(db_session, redis_client, handler)

    await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert captured["url"] == "https://api.example.com/users"


@pytest.mark.asyncio
async def test_process_task_uses_existing_chain_context(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200)

    test_task, test_run = await _build_task(db_session, url="https://example.com/me")

    run_context = RunContext(redis_client)
    await run_context.merge(test_run.id, {"authToken": "from-earlier-step"})

    api_request = (
        await db_session.execute(select(ApiRequest).where(ApiRequest.id == test_task.api_request_id))
    ).scalar_one()
    api_request.headers = {"Authorization": "Bearer {{authToken}}"}
    await db_session.flush()

    processor = _processor(db_session, redis_client, handler)
    await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert captured["auth_header"] == "Bearer from-earlier-step"

    await redis_client.delete(run_context.context_key(test_run.id))


@pytest.mark.asyncio
async def test_process_task_schedules_retry_on_transport_failure(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated failure", request=request)

    test_task, test_run = await _build_task(
        db_session, url="https://example.com/unreachable", retry_count=0, max_retries=3
    )
    zset_key = f"test:retry:{uuid.uuid4().hex[:12]}"
    retry_queue = RetryQueue(redis_client, zset_key=zset_key)
    processor = _processor(db_session, redis_client, handler, retry_queue=retry_queue)

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.new_status == TestTaskStatus.RETRYING
    assert outcome.retry_count == 1
    assert outcome.next_retry_at is not None

    score = await redis_client.zscore(zset_key, str(test_task.id))
    assert score is not None

    await redis_client.zrem(zset_key, str(test_task.id))


@pytest.mark.asyncio
async def test_process_task_fails_permanently_after_max_retries_exhausted(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated failure", request=request)

    test_task, test_run = await _build_task(
        db_session, url="https://example.com/unreachable", retry_count=3, max_retries=3
    )
    processor = _processor(db_session, redis_client, handler)

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.new_status == TestTaskStatus.FAILED
    assert outcome.next_retry_at is None


@pytest.mark.asyncio
async def test_process_task_fails_on_assertion_failure(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    test_task, test_run = await _build_task(
        db_session,
        url="https://example.com/missing",
        assertion_configs=[("status_code_equals", {"expected": 200})],
        max_retries=0,
    )
    processor = _processor(db_session, redis_client, handler)

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.assertions_passed is False
    assert outcome.new_status == TestTaskStatus.FAILED
    assert "assertion" in outcome.error_message.lower()


@pytest.mark.asyncio
async def test_process_task_raises_when_test_task_not_found(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    processor = _processor(db_session, redis_client, lambda request: httpx.Response(200))

    with pytest.raises(TaskProcessingError):
        await processor.process_task(uuid.uuid4(), worker_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_process_task_data_context_takes_precedence_over_chain_context(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200)

    test_task, test_run = await _build_task(
        db_session,
        url="{{baseUrl}}/users/{{userId}}",
        environment_variables={"baseUrl": "https://api.example.com"},
        data_context={"userId": "from-csv-row"},
    )

    run_context = RunContext(redis_client)
    await run_context.merge(test_run.id, {"userId": "from-chain-context"})

    processor = _processor(db_session, redis_client, handler)
    await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert captured["url"] == "https://api.example.com/users/from-csv-row"

    await redis_client.delete(run_context.context_key(test_run.id))


@pytest.mark.asyncio
async def test_process_task_isolates_extracted_variables_by_data_row(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        user_id = request.url.params.get("userId")
        return httpx.Response(200, json={"token": f"token-for-{user_id}"})

    test_task, test_run = await _build_task(db_session, url="https://example.com/login")
    test_task.data_row_index = 0
    test_task.data_context = {"userId": "row-0"}
    await db_session.flush()

    api_request = (
        await db_session.execute(select(ApiRequest).where(ApiRequest.id == test_task.api_request_id))
    ).scalar_one()
    api_request.extract_rules = [{"type": "json_path", "path": "$.token", "save_as": "authToken"}]
    api_request.query_params = {"userId": "{{userId}}"}
    await db_session.flush()

    processor = _processor(db_session, redis_client, handler)
    await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    run_context = RunContext(redis_client)
    row_0_context = await run_context.get_all(test_run.id, data_row_index=0)
    shared_context = await run_context.get_all(test_run.id)

    assert row_0_context == {"authToken": "token-for-row-0"}
    assert shared_context == {}

    await redis_client.delete(run_context.context_key(test_run.id, data_row_index=0))


@pytest.mark.asyncio
async def test_process_task_defers_when_rate_limited_without_calling_the_target(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200)

    host = f"host-{uuid.uuid4().hex[:12]}.example.com"
    test_task, test_run = await _build_task(db_session, url=f"https://{host}/get")
    rate_limiter = RateLimiter(redis_client, capacity=0, refill_rate=0.001)
    processor = _processor(db_session, redis_client, handler, rate_limiter=rate_limiter)

    with pytest.raises(RateLimitedError):
        await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert call_count["n"] == 0  # never reached the target at all

    await redis_client.delete(f"ratelimit:{host}")


@pytest.mark.asyncio
async def test_process_task_rate_limited_reschedules_without_consuming_a_retry(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    host = f"host-{uuid.uuid4().hex[:12]}.example.com"
    test_task, test_run = await _build_task(
        db_session, url=f"https://{host}/get", retry_count=0, max_retries=3
    )
    zset_key = f"test:retry:{uuid.uuid4().hex[:12]}"
    retry_queue = RetryQueue(redis_client, zset_key=zset_key)
    rate_limiter = RateLimiter(redis_client, capacity=0, refill_rate=0.001)
    processor = _processor(
        db_session, redis_client, handler, retry_queue=retry_queue, rate_limiter=rate_limiter
    )

    with pytest.raises(RateLimitedError):
        await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    score = await redis_client.zscore(zset_key, str(test_task.id))
    assert score is not None

    now = datetime.now(timezone.utc).timestamp()
    # Rescheduled ~1s out (RATE_LIMITED_RETRY_DELAY_SECONDS), a tight window
    # specifically to distinguish this from the exponential-backoff delay a
    # real failure at retry_count=0 would use (2s) -- these must not be the
    # same code path.
    assert now < score <= now + 2

    # The task's own row is completely untouched -- rate limiting isn't a
    # failure, so retry_count must not move and nothing should be RETRYING.
    await db_session.refresh(test_task)
    assert test_task.retry_count == 0
    assert test_task.status == TestTaskStatus.PENDING

    await redis_client.zrem(zset_key, str(test_task.id))
    await redis_client.delete(f"ratelimit:{host}")


@pytest.mark.asyncio
async def test_process_task_executes_normally_when_the_bucket_has_tokens(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    host = f"host-{uuid.uuid4().hex[:12]}.example.com"
    test_task, test_run = await _build_task(db_session, url=f"https://{host}/get")
    rate_limiter = RateLimiter(redis_client, capacity=5, refill_rate=1.0)
    processor = _processor(db_session, redis_client, handler, rate_limiter=rate_limiter)

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.new_status == TestTaskStatus.COMPLETED
    assert outcome.status_code == 200

    await redis_client.delete(f"ratelimit:{host}")


@pytest.mark.asyncio
async def test_process_task_ignores_rate_limiting_when_no_limiter_configured(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    """Default behavior (rate_limiter=None, matching rate_limit_enabled=False)
    is completely unaffected by this feature -- proven directly, not just
    inferred from every other pre-existing test in this file still passing
    unmodified."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    test_task, test_run = await _build_task(db_session, url="https://example.com/get")
    processor = _processor(db_session, redis_client, handler)  # no rate_limiter passed

    outcome = await processor.process_task(test_task.id, worker_id=uuid.uuid4())

    assert outcome.new_status == TestTaskStatus.COMPLETED