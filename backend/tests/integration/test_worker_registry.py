"""Direct (non-HTTP) tests for worker registration and heartbeat.

These call WorkerService the same way the worker process itself will --
verifying the Redis <-> Postgres consistency the service is responsible for
maintaining, not an HTTP response shape.
"""

import asyncio
import time

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository
from app.services.worker_service import WorkerService


def _make_service(
    db_session: AsyncSession, redis_client: Redis, ttl_seconds: int = 15
) -> WorkerService:
    return WorkerService(
        WorkerRepository(db_session), WorkerRegistry(redis_client, ttl_seconds=ttl_seconds)
    )


@pytest.mark.asyncio
async def test_register_creates_db_row_and_marks_alive(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    service = _make_service(db_session, redis_client)

    worker = await service.register(hostname="worker-a", pid=1234, capacity=10)

    assert worker.id is not None
    assert worker.hostname == "worker-a"
    assert worker.status.value == "online"
    assert await service.worker_registry.is_alive(worker.id) is True


@pytest.mark.asyncio
async def test_heartbeat_refreshes_liveness_and_records_history(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    service = _make_service(db_session, redis_client)
    worker = await service.register(hostname="worker-b", pid=2345, capacity=5)

    updated = await service.heartbeat(worker_id=worker.id, active_tasks_count=3, cpu_usage=12.5)

    assert updated.last_seen_at is not None
    assert await service.worker_registry.is_alive(worker.id) is True


@pytest.mark.asyncio
async def test_deregister_clears_liveness_but_keeps_db_row(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    service = _make_service(db_session, redis_client)
    worker = await service.register(hostname="worker-c", pid=3456, capacity=5)

    await service.deregister(worker_id=worker.id)

    assert await service.worker_registry.is_alive(worker.id) is False
    still_exists = await service.worker_repository.get_by_id(worker.id)
    assert still_exists is not None
    assert still_exists.status.value == "offline"


@pytest.mark.asyncio
async def test_worker_becomes_not_alive_after_ttl_expires(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    service = _make_service(db_session, redis_client, ttl_seconds=1)
    worker = await service.register(hostname="worker-d", pid=4567, capacity=5)

    key = service.worker_registry.alive_key(worker.id)
    ttl_ms_at_registration = await redis_client.pttl(key)
    assert 0 < ttl_ms_at_registration <= 1000, (
        f"Expected the alive key's TTL to be <=1000ms right after registration with "
        f"ttl_seconds=1, but Redis reports {ttl_ms_at_registration}ms."
    )

    assert await service.worker_registry.is_alive(worker.id) is True

    # Poll instead of a single fixed sleep-then-check. A hardcoded
    # asyncio.sleep(1.5) is exactly the kind of thing that gets less
    # reliable specifically under system load -- reliable alone, flaky
    # buried in the full suite -- which is the precise symptom this
    # replaces. Polling against Redis's own state, with a generous timeout,
    # verifies the same real behavior (the key actually expires) without
    # depending on one asyncio.sleep call's wake-up precision under load.
    deadline = time.monotonic() + 5.0
    is_alive = True
    while time.monotonic() < deadline:
        is_alive = await service.worker_registry.is_alive(worker.id)
        if not is_alive:
            break
        await asyncio.sleep(0.1)

    remaining_pttl = await redis_client.pttl(key)
    assert is_alive is False, (
        f"Expected worker.id to become not-alive within 5s of a 1s TTL, but "
        f"is_alive() was still True. Redis currently reports PTTL={remaining_pttl}ms "
        f"for this key."
    )


@pytest.mark.asyncio
async def test_list_workers_reports_live_and_dead_workers_correctly(
    db_session: AsyncSession, redis_client: Redis
) -> None:
    service = _make_service(db_session, redis_client, ttl_seconds=1)

    dying_worker = await service.register(hostname="worker-dying", pid=6789, capacity=5)

    dying_key = service.worker_registry.alive_key(dying_worker.id)
    ttl_ms_at_registration = await redis_client.pttl(dying_key)
    assert 0 < ttl_ms_at_registration <= 1000, (
        f"Expected dying_worker's alive key to have <=1000ms TTL right after "
        f"registration, got {ttl_ms_at_registration}ms."
    )

    # Same polling approach as test_worker_becomes_not_alive_after_ttl_expires,
    # for the same reason -- confirm real expiry via Redis's own state rather
    # than trust a single fixed sleep to have been long enough.
    deadline = time.monotonic() + 5.0
    dying_is_alive = True
    while time.monotonic() < deadline:
        dying_is_alive = await service.worker_registry.is_alive(dying_worker.id)
        if not dying_is_alive:
            break
        await asyncio.sleep(0.1)

    remaining_pttl = await redis_client.pttl(dying_key)
    assert dying_is_alive is False, (
        f"Expected dying_worker to become not-alive within 5s, but is_alive() "
        f"was still True. Redis currently reports PTTL={remaining_pttl}ms."
    )

    # live_worker is registered fresh, after dying_worker has already
    # expired -- its own TTL doesn't need to survive the same wait window.
    live_worker = await service.register(hostname="worker-live", pid=5678, capacity=5)

    entries = await service.list_workers()
    by_id = {entry["worker"].id: entry["is_alive"] for entry in entries}

    assert by_id[live_worker.id] is True
    assert by_id[dying_worker.id] is False