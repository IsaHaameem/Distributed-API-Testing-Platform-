"""Integration test for the retry-scheduling ZSET write path."""

import time
import uuid

import pytest
from redis.asyncio import Redis

from app.queue.retry_queue import RETRY_ZSET_KEY, RetryQueue


@pytest.mark.asyncio
async def test_schedule_retry_adds_task_with_correct_score(redis_client: Redis) -> None:
    queue = RetryQueue(redis_client)
    task_id = uuid.uuid4()
    next_attempt = time.time() + 30

    await queue.schedule_retry(task_id, next_attempt)

    score = await redis_client.zscore(RETRY_ZSET_KEY, str(task_id))
    assert score == pytest.approx(next_attempt, abs=1)

    await redis_client.zrem(RETRY_ZSET_KEY, str(task_id))


@pytest.mark.asyncio
async def test_scheduling_the_same_task_twice_updates_the_score(redis_client: Redis) -> None:
    queue = RetryQueue(redis_client)
    task_id = uuid.uuid4()

    await queue.schedule_retry(task_id, time.time() + 10)
    await queue.schedule_retry(task_id, time.time() + 50)

    members = await redis_client.zrangebyscore(RETRY_ZSET_KEY, "-inf", "+inf")
    assert members.count(str(task_id)) == 1  # not duplicated, score just updated

    await redis_client.zrem(RETRY_ZSET_KEY, str(task_id))