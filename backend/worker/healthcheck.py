"""Docker healthcheck for the worker container.

Deliberately does not invent a second liveness signal. WorkerRegistry
already answers "is this worker alive right now" via a single Redis TTL key
(worker:{id}:alive, refreshed on every heartbeat) -- the exact same signal
GET /workers already reports for every worker in the fleet. This script asks
that same question for this container's own worker, rather than building a
parallel mechanism (e.g. a locally-touched timestamp file) that could
disagree with it.

A plain process-existence check (e.g. pgrep) was considered and rejected: it
can only detect a crash, and Docker's own container exit status already
surfaces a crash without needing a HEALTHCHECK at all. The actual gap a
healthcheck exists to fill is a hang -- the process still running but making
no progress (for example, an await on a Postgres/Redis call that never
returns, which raises nothing and so isn't caught by any try/except). A hang
stops the heartbeat loop from completing cycles, which stops it from
refreshing the TTL key, which then expires in Redis on its own --
HEARTBEAT_TTL_SECONDS after the last real heartbeat -- with no separate
freshness-tracking logic needed here.

worker_id is only known at runtime, after registration succeeds, so the
worker persists its own id to WORKER_ID_FILE once at that point
(worker/main.py's _register()); this script just reads it back.
"""

import asyncio
import sys
from pathlib import Path
from uuid import UUID

from redis.asyncio import Redis

from app.core.redis_client import get_redis_client
from app.queue.worker_registry import WorkerRegistry

WORKER_ID_FILE = Path("/tmp/worker_id")


def read_worker_id(path: Path) -> UUID | None:
    """Not registered yet and unreadable/corrupt are treated the same way:
    not healthy, not an error worth crashing the check over."""
    if not path.exists():
        return None
    try:
        return UUID(path.read_text().strip())
    except ValueError:
        return None


async def is_healthy(path: Path = WORKER_ID_FILE, redis_client: Redis | None = None) -> bool:
    worker_id = read_worker_id(path)
    if worker_id is None:
        return False

    client = redis_client or get_redis_client()
    try:
        return await WorkerRegistry(client).is_alive(worker_id)
    finally:
        if redis_client is None:  # only close a connection we opened ourselves
            await client.aclose()


def main() -> None:
    healthy = asyncio.run(is_healthy())
    sys.exit(0 if healthy else 1)


if __name__ == "__main__":
    main()
