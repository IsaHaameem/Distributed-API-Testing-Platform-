"""Write side of the delayed-retry mechanism: a Redis sorted set holding
task references scored by their next-attempt Unix timestamp.

This is deliberately write-only for now. The sweep that scans for due
entries and re-enqueues them onto the main stream is the scheduler's job --
a distinct future milestone alongside the cron-schedule loop it naturally
belongs with. Building the write side now, without the reader, is safe:
entries just accumulate in the ZSET until something consumes them, which is
exactly the queuing behavior we want once that piece exists.
"""

from uuid import UUID

from redis.asyncio import Redis

RETRY_ZSET_KEY = "retry:pending"


def compute_backoff_seconds(retry_count: int) -> float:
    """Exponential backoff: 2s, 4s, 8s, 16s, 32s, capped at 60s."""
    return min(2 * (2**retry_count), 60)


class RetryQueue:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    async def schedule_retry(self, task_id: UUID, next_attempt_at_unix: float) -> None:
        """Record that `task_id` should be re-enqueued at or after the given
        Unix timestamp. Calling this again for the same task_id before it's
        been swept just updates the score -- ZADD is idempotent per member."""
        await self.redis.zadd(RETRY_ZSET_KEY, {str(task_id): next_attempt_at_unix})