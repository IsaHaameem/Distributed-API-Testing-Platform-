"""Integration tests for the worker healthcheck's is_healthy() against a
real Redis-backed WorkerRegistry -- proving the container healthcheck
reports exactly what GET /workers would report for the same worker, since
both go through the same WorkerRegistry.is_alive() call.
"""

import uuid
from pathlib import Path

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository
from app.services.worker_service import WorkerService
from worker.healthcheck import is_healthy


def _make_service(db_session: AsyncSession, redis_client: Redis) -> WorkerService:
    return WorkerService(WorkerRepository(db_session), WorkerRegistry(redis_client))


@pytest.mark.asyncio
async def test_is_healthy_true_for_a_registered_alive_worker(
    db_session: AsyncSession, redis_client: Redis, tmp_path: Path
) -> None:
    service = _make_service(db_session, redis_client)
    worker = await service.register(hostname="healthcheck-test", pid=1111, capacity=5)

    worker_id_file = tmp_path / "worker_id"
    worker_id_file.write_text(str(worker.id))

    assert await is_healthy(worker_id_file, redis_client=redis_client) is True


@pytest.mark.asyncio
async def test_is_healthy_false_after_deregistering(
    db_session: AsyncSession, redis_client: Redis, tmp_path: Path
) -> None:
    service = _make_service(db_session, redis_client)
    worker = await service.register(hostname="healthcheck-test-dead", pid=2222, capacity=5)
    await service.deregister(worker_id=worker.id)

    worker_id_file = tmp_path / "worker_id"
    worker_id_file.write_text(str(worker.id))

    assert await is_healthy(worker_id_file, redis_client=redis_client) is False


@pytest.mark.asyncio
async def test_is_healthy_false_when_worker_id_file_is_missing(
    redis_client: Redis, tmp_path: Path
) -> None:
    assert await is_healthy(tmp_path / "does_not_exist", redis_client=redis_client) is False


@pytest.mark.asyncio
async def test_is_healthy_false_for_an_id_with_no_matching_worker(
    redis_client: Redis, tmp_path: Path
) -> None:
    worker_id_file = tmp_path / "worker_id"
    worker_id_file.write_text(str(uuid.uuid4()))  # never registered

    assert await is_healthy(worker_id_file, redis_client=redis_client) is False
