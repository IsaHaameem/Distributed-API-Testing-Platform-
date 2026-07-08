"""Redis Streams queue: a consumer-group-backed task queue.

Producers XADD a lightweight reference (task_id, not the full task payload)
onto the stream; consumers in the same group compete for entries via
XREADGROUP, so each entry is delivered to exactly one live consumer.
Unacknowledged entries stay in that consumer's pending list (PEL) until
reclaimed via XAUTOCLAIM -- which is how a crashed worker's in-flight work
gets picked up by another one, without anyone polling or a human intervening.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from redis.asyncio import Redis
from redis.exceptions import ResponseError


@dataclass
class StreamEntry:
    entry_id: str
    task_id: UUID
    enqueued_at: datetime


class StreamQueue:
    def __init__(self, redis_client: Redis, stream_name: str, group_name: str) -> None:
        self.redis = redis_client
        self.stream_name = stream_name
        self.group_name = group_name

    async def ensure_group(self) -> None:
        """Idempotently create the stream and its consumer group."""
        try:
            await self.redis.xgroup_create(
                self.stream_name, self.group_name, id="0", mkstream=True
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, task_id: UUID) -> str:
        """Add a task reference to the stream. Returns the stream entry id."""
        return await self.redis.xadd(
            self.stream_name,
            {"task_id": str(task_id), "enqueued_at": datetime.now(timezone.utc).isoformat()},
        )

    async def consume(
        self, consumer_name: str, count: int = 1, block_ms: int = 1000
    ) -> list[StreamEntry]:
        """Read up to `count` new entries for this consumer. Blocks up to block_ms if none are ready."""
        result = await self.redis.xreadgroup(
            groupname=self.group_name,
            consumername=consumer_name,
            streams={self.stream_name: ">"},
            count=count,
            block=block_ms,
        )
        if not result:
            return []

        _stream_name, raw_entries = result[0]
        return [self._parse_entry(entry_id, fields) for entry_id, fields in raw_entries]

    async def ack(self, *entry_ids: str) -> int:
        """Acknowledge one or more entries, removing them from the group's pending list."""
        return await self.redis.xack(self.stream_name, self.group_name, *entry_ids)

    async def pending_count(self) -> int:
        """Total unacknowledged entries across all consumers in this group."""
        summary = await self.redis.xpending(self.stream_name, self.group_name)
        return summary["pending"] if summary else 0

    async def claim_stale(
        self, new_consumer_name: str, min_idle_ms: int, count: int = 10
    ) -> list[StreamEntry]:
        """Reassign entries idle longer than min_idle_ms to new_consumer_name.

        This is the failover mechanism: if a worker dies after XREADGROUP but
        before XACK, its entries sit unacknowledged forever unless something
        reclaims them. A periodic sweep calling this (the future scheduler's
        job) is what makes that recovery automatic.
        """
        _next_cursor, claimed, _deleted = await self.redis.xautoclaim(
            self.stream_name, self.group_name, new_consumer_name, min_idle_ms, "0", count=count
        )
        return [self._parse_entry(entry_id, fields) for entry_id, fields in claimed]

    @staticmethod
    def _parse_entry(entry_id: str, fields: dict[str, str]) -> StreamEntry:
        return StreamEntry(
            entry_id=entry_id,
            task_id=UUID(fields["task_id"]),
            enqueued_at=datetime.fromisoformat(fields["enqueued_at"]),
        )