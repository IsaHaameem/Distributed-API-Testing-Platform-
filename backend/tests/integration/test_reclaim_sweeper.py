"""Integration tests for the dead-consumer reclaim sweep -- the piece that
wires StreamQueue.claim_stale() (built and unit-tested since the streaming
queue was first written, but never called from anywhere in production) into
an actual running loop.

Uses isolated, unique-per-test stream/group names, same reasoning as every
other queue test since the test_run_orchestration.py fix -- this must never
touch the real test_tasks stream a running worker container consumes from.
"""

import asyncio
import time
import uuid

import pytest
from redis.asyncio import Redis

from app.queue.stream_client import StreamQueue
from scheduler.reclaim_sweeper import ReclaimSweeper


def _isolated_stream(redis_client: Redis) -> tuple[StreamQueue, str]:
    suffix = uuid.uuid4().hex[:12]
    stream_name = f"test:reclaim_sweeper:stream:{suffix}"
    group_name = f"test:reclaim_sweeper:group:{suffix}"
    return StreamQueue(redis_client, stream_name, group_name), stream_name


@pytest.mark.asyncio
async def test_sweep_once_reclaims_and_requeues_a_stale_entry(redis_client: Redis) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    task_id = uuid.uuid4()
    await stream_queue.enqueue(task_id)
    delivered = await stream_queue.consume("dead-consumer", count=1, block_ms=100)
    assert len(delivered) == 1
    old_entry_id = delivered[0].entry_id

    sweeper = ReclaimSweeper(stream_queue, min_idle_ms=0)
    reclaimed = await sweeper.sweep_once()

    assert reclaimed == 1

    # the old entry is acked (gone from the pending list)...
    entries = await stream_queue.consume("live-consumer", count=1, block_ms=100)
    # ...and a fresh entry for the same task_id is available to any live consumer
    assert len(entries) == 1
    assert entries[0].task_id == task_id
    assert entries[0].entry_id != old_entry_id

    await stream_queue.ack(entries[0].entry_id)
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_leaves_recently_delivered_entries_alone(redis_client: Redis) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    task_id = uuid.uuid4()
    await stream_queue.enqueue(task_id)
    await stream_queue.consume("live-worker", count=1, block_ms=100)

    # a generous idle threshold -- this entry was JUST delivered, nowhere near stale
    sweeper = ReclaimSweeper(stream_queue, min_idle_ms=60_000)
    reclaimed = await sweeper.sweep_once()

    assert reclaimed == 0
    assert await stream_queue.pending_count() == 1  # still owned by live-worker, untouched

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_handles_multiple_stale_entries(redis_client: Redis) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    task_ids = [uuid.uuid4() for _ in range(3)]
    for task_id in task_ids:
        await stream_queue.enqueue(task_id)
    await stream_queue.consume("dead-consumer", count=3, block_ms=100)

    sweeper = ReclaimSweeper(stream_queue, min_idle_ms=0)
    reclaimed = await sweeper.sweep_once()

    assert reclaimed == 3
    entries = await stream_queue.consume("live-consumer", count=3, block_ms=100)
    assert {e.task_id for e in entries} == set(task_ids)

    await stream_queue.ack(*(e.entry_id for e in entries))
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_returns_zero_when_nothing_is_pending(redis_client: Redis) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    sweeper = ReclaimSweeper(stream_queue, min_idle_ms=0)
    reclaimed = await sweeper.sweep_once()

    assert reclaimed == 0

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_leaves_entry_recoverable_after_a_failed_enqueue(
    redis_client: Redis, monkeypatch
) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    task_id = uuid.uuid4()
    await stream_queue.enqueue(task_id)
    await stream_queue.consume("dead-consumer", count=1, block_ms=100)

    async def failing_enqueue(task_id_arg):
        raise ConnectionError("simulated Redis failure")

    monkeypatch.setattr(stream_queue, "enqueue", failing_enqueue)

    sweeper = ReclaimSweeper(stream_queue, min_idle_ms=0)
    reclaimed = await sweeper.sweep_once()

    assert reclaimed == 0  # enqueue failed, nothing was successfully moved

    # the old entry was NOT acked (enqueue happens before ack) -- still
    # present in the pending list, recoverable on a later sweep, not lost
    assert await stream_queue.pending_count() == 1

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_run_forever_sweeps_repeatedly_until_shutdown(redis_client: Redis) -> None:
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    sweeper = ReclaimSweeper(stream_queue, interval_seconds=0.2, min_idle_ms=0)
    shutdown_event = asyncio.Event()
    loop_task = asyncio.create_task(sweeper.run_forever(shutdown_event))

    # Stale an entry *after* the loop has already done at least one empty
    # pass, to prove it's actually looping, not just sweeping once at startup.
    await asyncio.sleep(0.3)
    task_id = uuid.uuid4()
    await stream_queue.enqueue(task_id)
    await stream_queue.consume("dead-consumer", count=1, block_ms=100)

    deadline = time.monotonic() + 3.0
    found = False
    while time.monotonic() < deadline:
        entries = await stream_queue.consume("live-consumer", count=1, block_ms=100)
        if entries:
            found = True
            assert entries[0].task_id == task_id
            await stream_queue.ack(entries[0].entry_id)
            break

    shutdown_event.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert found, "run_forever did not pick up and reclaim a task staled after it started"

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_run_forever_survives_a_failed_sweep(redis_client: Redis, monkeypatch) -> None:
    """A single sweep raising shouldn't kill the whole loop -- the next
    interval should still run normally."""
    stream_queue, stream_name = _isolated_stream(redis_client)
    await stream_queue.ensure_group()

    sweeper = ReclaimSweeper(stream_queue, interval_seconds=0.2, min_idle_ms=0)

    call_count = {"n": 0}
    original_sweep_once = sweeper.sweep_once

    async def flaky_sweep_once():
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated transient failure")
        return await original_sweep_once()

    monkeypatch.setattr(sweeper, "sweep_once", flaky_sweep_once)

    shutdown_event = asyncio.Event()
    loop_task = asyncio.create_task(sweeper.run_forever(shutdown_event))

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline and call_count["n"] < 2:
        await asyncio.sleep(0.1)

    shutdown_event.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert call_count["n"] >= 2, "loop did not continue after the first sweep raised"

    await redis_client.delete(stream_name)
