"""Worker liveness signal, backed by a single TTL key per worker in Redis.

This is deliberately the only thing Redis is asked to remember about a
worker. The durable record -- hostname, pid, status, registration history --
lives in Postgres via WorkerRepository; Redis just answers "is this worker
alive right now," which is the one question that needs to be fast and
self-expiring rather than durable.
"""

from __future__ import annotations

from uuid import UUID

from redis.asyncio import Redis

HEARTBEAT_TTL_SECONDS = 15  # 3x the 5s heartbeat interval; tolerates one missed beat


class WorkerRegistry:
    def __init__(self, redis_client: Redis, ttl_seconds: int = HEARTBEAT_TTL_SECONDS) -> None:
        self.redis = redis_client
        self.ttl_seconds = ttl_seconds

    def alive_key(self, worker_id: UUID) -> str:
        return f"worker:{worker_id}:alive"

    async def mark_alive(self, worker_id: UUID) -> None:
        """Refresh a worker's liveness TTL. Called on registration and every heartbeat."""
        await self.redis.set(self.alive_key(worker_id), "1", ex=self.ttl_seconds)

    async def is_alive(self, worker_id: UUID) -> bool:
        return await self.redis.exists(self.alive_key(worker_id)) == 1

    async def deregister(self, worker_id: UUID) -> None:
        """Remove the liveness signal immediately, for graceful shutdown."""
        await self.redis.delete(self.alive_key(worker_id))