"""Integration tests for the retry-requeue sweep -- the piece that closes
the gap flagged since Step 10 Part 2: moving due entries from retry:pending
back onto the task stream so a scheduled retry actually happens.

Uses isolated, unique-per-test RetryQueue and StreamQueue instances, same
reasoning as every other queue test since the test_run_orchestration.py fix
-- this must never touch the real retry:pending key or the real test_tasks
stream a running worker container consumes from.
"""

import asyncio
import time
import uuid

import pytest
from redis.asyncio import Redis

from app.queue.retry_queue import RetryQueue
from app.queue.stream_client import StreamQueue
from scheduler.retry_sweeper import RetrySweeper


def _isolated_queues(redis_client: Redis) -> tuple[RetryQueue, StreamQueue, str, str]:
    suffix = uuid.uuid4().hex[:12]
    zset_key = f"test:retry_sweeper:zset:{suffix}"
    stream_name = f"test:retry_sweeper:stream:{suffix}"
    group_name = f"test:retry_sweeper:group:{suffix}"
    return (
        RetryQueue(redis_client, zset_key=zset_key),
        StreamQueue(redis_client, stream_name, group_name),
        zset_key,
        stream_name,
    )


@pytest.mark.asyncio
async def test_sweep_once_moves_due_entry_to_stream(redis_client: Redis) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()
    task_id = uuid.uuid4()
    await retry_queue.schedule_retry(task_id, time.time() - 1)  # already due

    sweeper = RetrySweeper(retry_queue, stream_queue)
    moved = await sweeper.sweep_once()

    assert moved == 1
    assert await redis_client.zscore(zset_key, str(task_id)) is None  # removed from the ZSET

    entries = await stream_queue.consume("test-consumer", count=1, block_ms=100)
    assert len(entries) == 1
    assert entries[0].task_id == task_id

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_leaves_not_yet_due_entries_alone(redis_client: Redis) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()
    task_id = uuid.uuid4()
    await retry_queue.schedule_retry(task_id, time.time() + 60)  # due a minute from now

    sweeper = RetrySweeper(retry_queue, stream_queue)
    moved = await sweeper.sweep_once()

    assert moved == 0
    assert await redis_client.zscore(zset_key, str(task_id)) is not None  # still there

    entries = await stream_queue.consume("test-consumer", count=1, block_ms=100)
    assert entries == []

    await redis_client.zrem(zset_key, str(task_id))
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_handles_multiple_due_entries(redis_client: Redis) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()
    task_ids = [uuid.uuid4() for _ in range(3)]
    for task_id in task_ids:
        await retry_queue.schedule_retry(task_id, time.time() - 1)

    sweeper = RetrySweeper(retry_queue, stream_queue)
    moved = await sweeper.sweep_once()

    assert moved == 3
    entries = await stream_queue.consume("test-consumer", count=3, block_ms=100)
    assert {e.task_id for e in entries} == set(task_ids)

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_returns_zero_when_nothing_is_due(redis_client: Redis) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()

    sweeper = RetrySweeper(retry_queue, stream_queue)
    moved = await sweeper.sweep_once()

    assert moved == 0

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_sweep_once_reschedules_a_task_if_enqueue_fails(redis_client: Redis, monkeypatch) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()
    task_id = uuid.uuid4()
    await retry_queue.schedule_retry(task_id, time.time() - 1)

    async def failing_enqueue(task_id_arg):
        raise ConnectionError("simulated Redis failure")

    monkeypatch.setattr(stream_queue, "enqueue", failing_enqueue)

    sweeper = RetrySweeper(retry_queue, stream_queue)
    moved = await sweeper.sweep_once()

    assert moved == 0  # the enqueue failed, so nothing was successfully moved
    score = await redis_client.zscore(zset_key, str(task_id))
    assert score is not None  # but it was rescheduled, not lost

    await redis_client.zrem(zset_key, str(task_id))
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_run_forever_sweeps_repeatedly_until_shutdown(redis_client: Redis) -> None:
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()

    sweeper = RetrySweeper(retry_queue, stream_queue, interval_seconds=0.2)
    shutdown_event = asyncio.Event()
    loop_task = asyncio.create_task(sweeper.run_forever(shutdown_event))

    # Schedule something due *after* the loop has already started and done
    # at least one empty pass, to prove it's actually looping, not just
    # sweeping once at startup.
    await asyncio.sleep(0.3)
    task_id = uuid.uuid4()
    await retry_queue.schedule_retry(task_id, time.time() - 1)

    deadline = time.monotonic() + 3.0
    found = False
    while time.monotonic() < deadline:
        entries = await stream_queue.consume("test-consumer", count=1, block_ms=100)
        if entries:
            found = True
            assert entries[0].task_id == task_id
            break

    shutdown_event.set()
    await asyncio.wait_for(loop_task, timeout=2)

    assert found, "run_forever did not pick up and sweep a task scheduled after it started"

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_run_forever_survives_a_failed_sweep(redis_client: Redis, monkeypatch) -> None:
    """A single sweep raising shouldn't kill the whole loop -- the next
    interval should still run normally."""
    retry_queue, stream_queue, zset_key, stream_name = _isolated_queues(redis_client)
    await stream_queue.ensure_group()

    sweeper = RetrySweeper(retry_queue, stream_queue, interval_seconds=0.2)

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