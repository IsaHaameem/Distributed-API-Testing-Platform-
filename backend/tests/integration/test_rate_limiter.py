"""Integration tests for RateLimiter's token bucket -- real Redis, since the
bucket math runs entirely inside a Lua script executed server-side (using
Redis's own TIME command, not a client-supplied timestamp, deliberately --
see the module docstring in app/queue/rate_limiter.py for why).

Every test uses a unique, fake per-test hostname as the bucket key, the same
"unique per-test Redis key" discipline used for every other queue/stream
test in this project -- a real host name would risk two tests racing the
same bucket.
"""

import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from app.queue.rate_limiter import BUCKET_KEY_PREFIX, RateLimiter


def _fake_host() -> str:
    return f"host-{uuid.uuid4().hex[:12]}.example.com"


@pytest.mark.asyncio
async def test_try_acquire_succeeds_within_capacity(redis_client: Redis) -> None:
    host = _fake_host()
    limiter = RateLimiter(redis_client, capacity=5, refill_rate=1.0)

    for _ in range(5):
        assert await limiter.try_acquire(host) is True

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_try_acquire_denies_once_capacity_is_exhausted(redis_client: Redis) -> None:
    host = _fake_host()
    limiter = RateLimiter(redis_client, capacity=2, refill_rate=0.001)  # effectively no refill

    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is False  # bucket is empty

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_denied_acquire_does_not_consume_a_token(redis_client: Redis) -> None:
    host = _fake_host()
    limiter = RateLimiter(redis_client, capacity=1, refill_rate=0.001)

    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is False
    assert await limiter.try_acquire(host) is False  # still denied, not further depleted

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_tokens_refill_over_time(redis_client: Redis) -> None:
    host = _fake_host()
    limiter = RateLimiter(redis_client, capacity=1, refill_rate=10.0)  # fast refill for a quick test

    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is False  # bucket empty

    await asyncio.sleep(0.3)  # 10 tokens/sec * 0.3s = ~3 tokens worth of refill, capped at capacity=1

    assert await limiter.try_acquire(host) is True

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_refill_is_capped_at_capacity(redis_client: Redis) -> None:
    host = _fake_host()
    limiter = RateLimiter(redis_client, capacity=2, refill_rate=100.0)  # would refill far past capacity

    await limiter.try_acquire(host)  # consume one, to establish a timestamp in the bucket
    await asyncio.sleep(0.2)  # plenty of time to refill "past" capacity if uncapped

    # only 2 should ever be acquirable in a row, never more, regardless of elapsed time
    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is True
    assert await limiter.try_acquire(host) is False

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_different_hosts_have_independent_buckets(redis_client: Redis) -> None:
    host_a, host_b = _fake_host(), _fake_host()
    limiter = RateLimiter(redis_client, capacity=1, refill_rate=0.001)

    assert await limiter.try_acquire(host_a) is True
    assert await limiter.try_acquire(host_a) is False  # host_a exhausted

    assert await limiter.try_acquire(host_b) is True  # host_b untouched, has its own bucket

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host_a}")
    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host_b}")


@pytest.mark.asyncio
async def test_two_rate_limiter_instances_share_the_same_bucket_for_the_same_host(
    redis_client: Redis,
) -> None:
    """Proves the distributed-safety claim directly: two separate
    RateLimiter objects (standing in for two separate worker processes)
    pointed at the same Redis and the same host correctly compete for one
    shared pool of tokens, not two independent ones."""
    host = _fake_host()
    limiter_a = RateLimiter(redis_client, capacity=2, refill_rate=0.001)
    limiter_b = RateLimiter(redis_client, capacity=2, refill_rate=0.001)

    assert await limiter_a.try_acquire(host) is True
    assert await limiter_b.try_acquire(host) is True
    assert await limiter_a.try_acquire(host) is False  # the shared bucket is now empty
    assert await limiter_b.try_acquire(host) is False

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")


@pytest.mark.asyncio
async def test_concurrent_acquires_never_over_grant_beyond_capacity(redis_client: Redis) -> None:
    """The atomicity claim, proven directly: fire more concurrent acquire
    attempts than the bucket has capacity for, and confirm exactly `capacity`
    of them succeed -- not more, which is what a race condition (read tokens,
    then write tokens, non-atomically) would produce under real concurrency."""
    host = _fake_host()
    capacity = 5
    limiter = RateLimiter(redis_client, capacity=capacity, refill_rate=0.001)

    results = await asyncio.gather(*(limiter.try_acquire(host) for _ in range(20)))

    assert sum(1 for allowed in results if allowed) == capacity

    await redis_client.delete(f"{BUCKET_KEY_PREFIX}{host}")
