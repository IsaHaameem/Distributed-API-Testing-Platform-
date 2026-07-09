"""Integration tests for the worker process entrypoint -- the only tests in
this milestone that run the actual consume-process-write-ack loop against a
real (test-isolated) stream, real Redis, and real Postgres.

These poll for the expected outcome with a generous timeout rather than
sleep-then-check-once, for the same reason the worker_registry tests were
fixed that way: a fixed sleep is exactly the kind of thing that's reliable
alone and flaky under load, and polling tests the identical real behavior
without betting on one sleep call's wake-up precision.
"""

import asyncio
import time
import uuid

import httpx
import pytest
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models.api_request import ApiRequest
from app.models.collection import Collection
from app.models.enums import HttpMethod, OrganizationRole, TestRunStatus, TestRunType, TestTaskStatus
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.project import Project
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User
from app.models.worker import Worker
from app.queue.rate_limiter import RateLimiter
from scheduler.reclaim_sweeper import ReclaimSweeper
from worker.main import WorkerProcess


def _unique_stream_names() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:12]
    return f"test:worker_main:stream:{suffix}", f"test:worker_main:group:{suffix}"


async def _build_task(session: AsyncSession) -> tuple[TestTask, TestRun]:
    user = User(
        email=f"main-test-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("a-strong-password-123"),
        full_name="Main Test User",
    )
    session.add(user)
    await session.flush()

    org = Organization(name="Main Test Org", slug=f"main-test-{uuid.uuid4().hex[:12]}")
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
        collection_id=collection.id, name="Request", method=HttpMethod.GET, url="https://example.com/ok"
    )
    session.add(api_request)
    await session.flush()

    test_run = TestRun(
        collection_id=collection.id,
        initiated_by=user.id,
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=1,
        config={"environment_variables": {}},
    )
    session.add(test_run)
    await session.flush()

    test_task = TestTask(test_run_id=test_run.id, api_request_id=api_request.id)
    session.add(test_task)
    await session.flush()

    return test_task, test_run


@pytest.mark.asyncio
async def test_worker_process_consumes_processes_writes_and_acks_a_real_task(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(db_session)
    await db_session.commit()  # the worker uses a separate session -- must actually be committed

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 8.0
    completed = False
    while time.monotonic() < deadline:
        await db_session.refresh(test_task)
        if test_task.status == TestTaskStatus.COMPLETED:
            completed = True
            break
        await asyncio.sleep(0.2)

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    assert completed, "worker did not complete the task within 8 seconds"

    result = (
        await db_session.execute(select(RequestResult).where(RequestResult.test_task_id == test_task.id))
    ).scalar_one()
    assert result.status_code == 200

    worker_row = (
        await db_session.execute(select(Worker).where(Worker.id == process.worker_id))
    ).scalar_one()
    assert worker_row.status.value == "offline"  # deregistered cleanly on shutdown

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_worker_process_registers_and_deregisters_cleanly_with_no_tasks(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))),
    )

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and process.worker_id is None:
        await asyncio.sleep(0.1)

    assert process.worker_id is not None, "worker did not register within 5 seconds"
    worker_id = process.worker_id

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    worker_row = (await db_session.execute(select(Worker).where(Worker.id == worker_id))).scalar_one()
    assert worker_row.status.value == "offline"

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_worker_process_acks_and_records_a_failed_task(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated failure", request=request)

    test_task, test_run = await _build_task(db_session)
    test_task.max_retries = 0  # force permanent failure on the first attempt, not a retry
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 8.0
    finished = False
    while time.monotonic() < deadline:
        await db_session.refresh(test_task)
        if test_task.status == TestTaskStatus.FAILED:
            finished = True
            break
        await asyncio.sleep(0.2)

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    assert finished, "task did not reach FAILED status within 8 seconds"

    pending_count = await process.stream_queue.pending_count()
    assert pending_count == 0  # acked, not left stuck in the pending list

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_consume_loop_survives_a_failed_write_batch(
    db_session: AsyncSession, redis_client: Redis, monkeypatch
) -> None:
    """A transient Postgres/Redis error while writing a batch must not crash
    the worker process -- only the affected entries should stay stuck in the
    pending list, unacked, for the reclaim sweep to recover later."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(db_session)
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    call_count = {"n": 0}

    async def flaky_write_batch(outcomes, session):
        call_count["n"] += 1
        raise ConnectionError("simulated transient Postgres failure")

    monkeypatch.setattr(process.result_writer, "write_batch", flaky_write_batch)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and call_count["n"] < 1:
        await asyncio.sleep(0.1)
    assert call_count["n"] >= 1, "write_batch was never attempted"

    # give the loop a moment to finish handling the failure before asserting
    await asyncio.sleep(0.3)

    assert not run_task.done(), "worker process crashed on a transient write failure"

    await db_session.refresh(test_task)
    assert test_task.status == TestTaskStatus.PENDING  # unchanged -- nothing was written

    assert await process.stream_queue.pending_count() == 1  # stuck, unacked, not lost

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_consume_loop_survives_a_failed_ack(
    db_session: AsyncSession, redis_client: Redis, monkeypatch
) -> None:
    """A transient failure acking an already-written batch must not crash
    the worker -- the write already landed; only the ack is at risk."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(db_session)
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    async def failing_ack(*entry_ids):
        raise ConnectionError("simulated transient Redis failure")

    monkeypatch.setattr(process.stream_queue, "ack", failing_ack)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 8.0
    completed = False
    while time.monotonic() < deadline:
        await db_session.refresh(test_task)
        if test_task.status == TestTaskStatus.COMPLETED:
            completed = True
            break
        await asyncio.sleep(0.2)

    assert completed, "task did not complete within 8 seconds"
    assert not run_task.done(), "worker process crashed on a transient ack failure"

    # the write landed even though ack failed -- entry stays pending, not lost
    assert await process.stream_queue.pending_count() == 1

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_worker_recovers_a_stuck_task_via_reclaim_sweep_after_a_write_failure(
    db_session: AsyncSession, redis_client: Redis, monkeypatch
) -> None:
    """End-to-end proof of the whole worker-reliability design: a transient
    write failure doesn't crash the worker (crash resilience), and the
    reclaim sweep (dead-consumer reclaim) is what actually recovers the
    stuck task afterward -- the same still-running worker picks the freshly
    re-enqueued copy back up and finishes it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(db_session)
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    call_count = {"n": 0}
    original_write_batch = process.result_writer.write_batch

    async def flaky_write_batch(outcomes, session):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise ConnectionError("simulated transient Postgres failure")
        return await original_write_batch(outcomes, session)

    monkeypatch.setattr(process.result_writer, "write_batch", flaky_write_batch)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and call_count["n"] < 1:
        await asyncio.sleep(0.1)
    assert call_count["n"] >= 1, "write_batch was never attempted"
    await asyncio.sleep(0.3)

    assert not run_task.done(), "worker process crashed on a transient write failure"
    assert await process.stream_queue.pending_count() == 1

    # Simulate the reclaim sweep noticing and recovering the stuck entry --
    # min_idle_ms=0 stands in for "enough time has passed" in this test.
    reclaim_sweeper = ReclaimSweeper(process.stream_queue, min_idle_ms=0)
    reclaimed = await reclaim_sweeper.sweep_once()
    assert reclaimed == 1

    deadline = time.monotonic() + 8.0
    completed = False
    while time.monotonic() < deadline:
        await db_session.refresh(test_task)
        if test_task.status == TestTaskStatus.COMPLETED:
            completed = True
            break
        await asyncio.sleep(0.2)

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    assert completed, "task was not recovered and completed after the reclaim sweep"

    await redis_client.delete(stream_name)


async def _build_two_tasks_same_host(db_session: AsyncSession, host: str) -> tuple[TestTask, TestTask]:
    user = User(
        email=f"ratelimit-test-{uuid.uuid4()}@example.com",
        hashed_password=hash_password("a-strong-password-123"),
        full_name="Rate Limit Test User",
    )
    db_session.add(user)
    await db_session.flush()

    org = Organization(name="Rate Limit Org", slug=f"ratelimit-{uuid.uuid4().hex[:12]}")
    db_session.add(org)
    await db_session.flush()
    db_session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=OrganizationRole.OWNER))

    project = Project(organization_id=org.id, name="Project", created_by=user.id)
    db_session.add(project)
    await db_session.flush()

    collection = Collection(project_id=project.id, name="Collection")
    db_session.add(collection)
    await db_session.flush()

    api_request = ApiRequest(
        collection_id=collection.id, name="Request", method=HttpMethod.GET, url=f"https://{host}/ok"
    )
    db_session.add(api_request)
    await db_session.flush()

    test_run = TestRun(
        collection_id=collection.id,
        initiated_by=user.id,
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=2,
        config={"environment_variables": {}},
    )
    db_session.add(test_run)
    await db_session.flush()

    task_a = TestTask(test_run_id=test_run.id, api_request_id=api_request.id)
    task_b = TestTask(test_run_id=test_run.id, api_request_id=api_request.id)
    db_session.add_all([task_a, task_b])
    await db_session.flush()

    return task_a, task_b


@pytest.mark.asyncio
async def test_worker_rate_limits_concurrent_tasks_targeting_the_same_host(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    """Two tasks in the same batch, targeting the same host, with a bucket
    that can satisfy only one of them immediately -- proves the rate limiter
    is actually wired into the live consume loop, not just correct in
    isolation: exactly one request reaches the target, the other is
    deferred without ever calling out and without being lost."""
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(200, json={"status": "ok"})

    host = f"host-{uuid.uuid4().hex[:12]}.example.com"
    task_a, task_b = await _build_two_tasks_same_host(db_session, host)
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    rate_limiter = RateLimiter(redis_client, capacity=1, refill_rate=0.001)  # effectively no refill
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        rate_limiter=rate_limiter,
    )
    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(task_a.id)
    await process.stream_queue.enqueue(task_b.id)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        await db_session.refresh(task_a)
        await db_session.refresh(task_b)
        if TestTaskStatus.COMPLETED in (task_a.status, task_b.status):
            break
        await asyncio.sleep(0.2)

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    completed = [t for t in (task_a, task_b) if t.status == TestTaskStatus.COMPLETED]
    deferred = [t for t in (task_a, task_b) if t.status == TestTaskStatus.PENDING]

    assert len(completed) == 1, "expected exactly one task to complete immediately"
    assert len(deferred) == 1, "expected exactly one task to remain deferred, its row untouched"
    assert call_count["n"] == 1, "the target host must have been called exactly once, not twice"

    await redis_client.delete(stream_name)
    await redis_client.delete(f"ratelimit:{host}")


@pytest.mark.asyncio
async def test_worker_process_ignores_rate_limiting_when_no_rate_limiter_is_configured(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    """Default construction (no rate_limiter argument, matching
    rate_limit_enabled=False) behaves exactly as it did before this feature
    existed -- proven directly at the WorkerProcess level, not just inferred
    from every pre-existing test in this file still passing unmodified."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"})

    test_task, test_run = await _build_task(db_session)
    await db_session.commit()

    stream_name, group_name = _unique_stream_names()
    process = WorkerProcess(
        stream_name=stream_name,
        consumer_group=group_name,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert process.rate_limiter is None  # settings-driven default: disabled

    await process.stream_queue.ensure_group()
    await process.stream_queue.enqueue(test_task.id)

    run_task = asyncio.create_task(process.start())

    deadline = time.monotonic() + 8.0
    completed = False
    while time.monotonic() < deadline:
        await db_session.refresh(test_task)
        if test_task.status == TestTaskStatus.COMPLETED:
            completed = True
            break
        await asyncio.sleep(0.2)

    process.request_shutdown()
    await asyncio.wait_for(run_task, timeout=10)

    assert completed, "task did not complete within 8 seconds with rate limiting disabled"

    await redis_client.delete(stream_name)