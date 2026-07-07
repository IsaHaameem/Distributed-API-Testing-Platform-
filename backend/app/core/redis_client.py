"""Shared Redis connection pool."""

import redis.asyncio as redis

from app.config import get_settings

settings = get_settings()

redis_pool: redis.ConnectionPool = redis.ConnectionPool.from_url(
    settings.redis_url,
    decode_responses=True,
    max_connections=50,
)


def get_redis_client() -> redis.Redis:
    """Return a Redis client bound to the shared connection pool."""
    return redis.Redis(connection_pool=redis_pool)