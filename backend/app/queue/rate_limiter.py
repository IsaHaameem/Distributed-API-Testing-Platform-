"""Distributed token-bucket rate limiter, one bucket per target host.

Nothing in this project previously stopped a worker from hammering a target
API under test -- named explicitly in the original spec and designed for
(a Redis token bucket per host) since Step 1, but never built. This is that.

The check-refill-consume sequence runs as a single Lua script (EVAL), which
Redis executes atomically -- this is what makes it correct across multiple
concurrently-running workers, or multiple concurrently-processed tasks
within one worker's own batch (worker/main.py processes a batch via
asyncio.gather): every caller, from anywhere, competes for the same bucket
with no race window between reading the current token count and writing the
new one.

The script uses Redis's own TIME command as its clock, not a timestamp
passed in from the calling process. Two different workers (or the same
worker across container restarts) can have host clocks that disagree by a
meaningful amount -- this project has already spent real debugging time on
exactly that class of problem (see PROJECT_KNOWLEDGE.md's WSL2 clock-skew
investigation). A single, server-authoritative clock for the bucket math
sidesteps it entirely rather than risking a repeat.
"""

from __future__ import annotations

from urllib.parse import urlparse

from redis.asyncio import Redis
from redis.commands.core import AsyncScript

BUCKET_KEY_PREFIX = "ratelimit:"
BUCKET_TTL_SECONDS = 3600  # housekeeping only -- a host not queried in an hour doesn't need its bucket kept

_TOKEN_BUCKET_SCRIPT = """
local bucket_key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl_seconds = tonumber(ARGV[4])

local time_result = redis.call("TIME")
local now = tonumber(time_result[1]) + tonumber(time_result[2]) / 1000000

local bucket = redis.call("HMGET", bucket_key, "tokens", "timestamp")
local tokens = tonumber(bucket[1])
local timestamp = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    timestamp = now
end

local elapsed = math.max(0, now - timestamp)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call("HMSET", bucket_key, "tokens", tostring(tokens), "timestamp", tostring(now))
redis.call("EXPIRE", bucket_key, ttl_seconds)

return allowed
"""


class RateLimiter:
    def __init__(self, redis_client: Redis, *, capacity: int, refill_rate: float) -> None:
        self.redis = redis_client
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._script: AsyncScript = redis_client.register_script(_TOKEN_BUCKET_SCRIPT)

    @staticmethod
    def host_for_url(url: str) -> str | None:
        """The bucket key for a URL is its host -- every request to the same
        target API shares one bucket, regardless of path/query. Returns None
        for a URL with no parseable host (callers should treat that as
        "nothing to rate-limit against" rather than fail)."""
        return urlparse(url).hostname or None

    async def try_acquire(self, host: str, *, tokens: int = 1) -> bool:
        """Attempt to consume `tokens` from `host`'s bucket. Returns True and
        consumes them if enough were available; returns False (consuming
        nothing) otherwise. Never blocks or raises for "not enough tokens" --
        that's an expected, routine outcome, not an error."""
        bucket_key = f"{BUCKET_KEY_PREFIX}{host}"
        allowed = await self._script(
            keys=[bucket_key],
            args=[self.capacity, self.refill_rate, tokens, BUCKET_TTL_SECONDS],
        )
        return bool(allowed)
