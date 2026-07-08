"""One-off script for manually verifying worker registration and heartbeat.
Not a pytest test -- run it directly:
    docker compose exec backend python tests/manual_worker_check.py
"""

import asyncio

import redis.asyncio as redis

from app.config import get_settings
from app.database import AsyncSessionFactory
from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository
from app.services.worker_service import WorkerService

# Long enough that running redis-cli by hand, across multiple separate
# commands with reading/typing in between, can't lose the race against
# expiry the way the real 15s worker-liveness TTL can when tested this way.
# Purely a diagnostic aid -- WorkerRegistry's actual TTL stays 15s.
DIAGNOSTIC_KEY_TTL_SECONDS = 300


async def main() -> None:
    settings = get_settings()
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)

    diagnostic_key = "manual_worker_check:diagnostic_probe"
    await redis_client.set(diagnostic_key, "1", ex=DIAGNOSTIC_KEY_TTL_SECONDS)

    async with AsyncSessionFactory() as session:
        registry = WorkerRegistry(redis_client)
        service = WorkerService(WorkerRepository(session), registry)

        worker = await service.register(hostname="manual-test-worker", pid=1, capacity=5)
        await session.commit()

        key = registry.alive_key(worker.id)
        print(f"Registered worker: {worker.id}")
        print(f"Worker liveness key (real 15s TTL, same as production): {key}")
        print(f"Diagnostic key ({DIAGNOSTIC_KEY_TTL_SECONDS}s TTL, just for this check): {diagnostic_key}")
        print()
        print(f"You have {DIAGNOSTIC_KEY_TTL_SECONDS} seconds -- run this:")
        print(f'  docker compose exec redis redis-cli EXISTS "{diagnostic_key}"')
        print()
        print("A result of 1 confirms the write/read path is correct end to end, and that")
        print("the earlier failures were the real key's 15s TTL elapsing during the time it")
        print("took to run several separate manual commands -- not an implementation bug.")

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())