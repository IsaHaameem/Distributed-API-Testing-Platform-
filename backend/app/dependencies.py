"""Shared FastAPI dependencies. Routers should import Depends() targets from here."""

from collections.abc import AsyncGenerator

from redis.asyncio import Redis

from app.core.redis_client import get_redis_client
from app.database import get_db

__all__ = ["get_db", "get_redis"]


async def get_redis() -> AsyncGenerator[Redis, None]:
    """Yield a Redis client for the duration of a request."""
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()