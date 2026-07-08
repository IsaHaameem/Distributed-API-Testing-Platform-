"""Shared chain-variable context for a test run, backed by a Redis hash.

Workers are stateless -- a chained request's step 2 might execute on a
completely different worker than step 1. This hash is how a variable
extracted in step 1 becomes visible to whichever worker picks up step 2,
regardless of which process that is.
"""

from uuid import UUID

from redis.asyncio import Redis

CONTEXT_TTL_SECONDS = 24 * 60 * 60  # a run still "in progress" after a day is abandoned, not slow


class RunContext:
    def __init__(self, redis_client: Redis) -> None:
        self.redis = redis_client

    def context_key(self, test_run_id: UUID) -> str:
        return f"run:{test_run_id}:context"

    async def get_all(self, test_run_id: UUID) -> dict[str, str]:
        """Return every variable extracted so far in this run."""
        return await self.redis.hgetall(self.context_key(test_run_id))

    async def merge(self, test_run_id: UUID, variables: dict[str, str]) -> None:
        """Merge newly-extracted variables into the run's shared context and
        refresh its TTL. Safe to call from multiple tasks concurrently --
        HSET is atomic per call, though if two chain steps happen to extract
        the same variable name, the last one to merge wins."""
        if not variables:
            return
        key = self.context_key(test_run_id)
        await self.redis.hset(key, mapping=variables)
        await self.redis.expire(key, CONTEXT_TTL_SECONDS)