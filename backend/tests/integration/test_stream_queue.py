"""Direct (non-HTTP) tests for the Redis Streams task queue.

This is the core distributed-systems mechanism: competing consumers via a
consumer group, and failover via XAUTOCLAIM when a consumer dies mid-task.
Neither is observable through an HTTP request/response cycle, so these talk
to Redis directly, the same way a worker process will.
"""

import uuid

import pytest
from redis.asyncio import Redis

from app.queue.stream_client import StreamQueue


def _unique_stream() -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:12]
    return f"test:stream:{suffix}", f"test:group:{suffix}"


@pytest.mark.asyncio
async def test_ensure_group_is_idempotent(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)

    await queue.ensure_group()
    await queue.ensure_group()  # must not raise

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_enqueue_and_consume_single_task(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    task_id = uuid.uuid4()
    await queue.enqueue(task_id)

    entries = await queue.consume("consumer-1", count=1, block_ms=100)

    assert len(entries) == 1
    assert entries[0].task_id == task_id

    await queue.ack(entries[0].entry_id)
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_consume_returns_empty_when_stream_is_empty(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    entries = await queue.consume("consumer-1", count=1, block_ms=100)

    assert entries == []

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_multiple_consumers_split_the_work(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    task_a, task_b = uuid.uuid4(), uuid.uuid4()
    await queue.enqueue(task_a)
    await queue.enqueue(task_b)

    entries_a = await queue.consume("consumer-a", count=1, block_ms=100)
    entries_b = await queue.consume("consumer-b", count=1, block_ms=100)

    delivered = {entries_a[0].task_id, entries_b[0].task_id}
    assert delivered == {task_a, task_b}  # each task delivered exactly once, to a different consumer

    await queue.ack(entries_a[0].entry_id, entries_b[0].entry_id)
    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_unacked_entry_remains_pending(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    await queue.enqueue(uuid.uuid4())
    await queue.consume("consumer-1", count=1, block_ms=100)

    assert await queue.pending_count() == 1

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_ack_removes_entry_from_pending(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    await queue.enqueue(uuid.uuid4())
    entries = await queue.consume("consumer-1", count=1, block_ms=100)
    await queue.ack(entries[0].entry_id)

    assert await queue.pending_count() == 0

    await redis_client.delete(stream_name)


@pytest.mark.asyncio
async def test_claim_stale_reassigns_a_dead_consumers_entry(redis_client: Redis) -> None:
    stream_name, group_name = _unique_stream()
    queue = StreamQueue(redis_client, stream_name, group_name)
    await queue.ensure_group()

    task_id = uuid.uuid4()
    await queue.enqueue(task_id)

    # consumer-dead reads it and, hypothetically, crashes before acking
    delivered = await queue.consume("consumer-dead", count=1, block_ms=100)
    assert len(delivered) == 1

    # a live consumer sweeps for anything idle 0ms or more -- i.e. everything pending
    reclaimed = await queue.claim_stale("consumer-alive", min_idle_ms=0)

    assert len(reclaimed) == 1
    assert reclaimed[0].task_id == task_id
    assert reclaimed[0].entry_id == delivered[0].entry_id

    await queue.ack(reclaimed[0].entry_id)
    await redis_client.delete(stream_name)