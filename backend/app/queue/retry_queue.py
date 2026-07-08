"""Write and read sides of the delayed-retry mechanism: a Redis sorted set
holding task references scored by their next-attempt Unix timestamp.

The write side (schedule_retry) has existed since Step 10 Part 2. pop_due,
the read side, is new this milestone -- it's what the retry sweeper
(scheduler/retry_sweeper.py) uses to find and reclaim entries whose time
has come.
"""

from uuid import UUID

from redis.asyncio import Redis

RETRY_ZSET_KEY = "retry:pending"


def compute_backoff_seconds(retry_count: int) -> float:
    """Exponential backoff: 2s, 4s, 8s, 16s, 32s, capped at 60s."""
    return min(2 * (2**retry_count), 60)


class RetryQueue:
    def __init__(self, redis_client: Redis, zset_key: str = RETRY_ZSET_KEY) -> None:
        self.redis = redis_client
        self.zset_key = zset_key

    async def schedule_retry(self, task_id: UUID, next_attempt_at_unix: float) -> None:
        """Record that `task_id` should be re-enqueued at or after the given
        Unix timestamp. Calling this again for the same task_id before it's
        been swept just updates the score -- ZADD is idempotent per member."""
        await self.redis.zadd(self.zset_key, {str(task_id): next_attempt_at_unix})

    async def pop_due(self, now_unix: float, limit: int = 100) -> list[UUID]:
        """Remove and return every task_id whose scheduled retry time has
        passed (score <= now_unix), oldest first, up to `limit`.

        Correct for a single scheduler instance: read-then-remove,
        sequential, nothing else reading concurrently. Running more than one
        scheduler instance at once would need this to be atomic across
        processes -- e.g. a Lua script -- which isn't needed yet, since
        nothing in this project runs more than one scheduler.
        """
        due_members = await self.redis.zrangebyscore(
            self.zset_key, "-inf", now_unix, start=0, num=limit
        )
        if not due_members:
            return []
        await self.redis.zrem(self.zset_key, *due_members)
        return [UUID(member) for member in due_members]