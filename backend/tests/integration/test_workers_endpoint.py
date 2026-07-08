"""Integration tests for the read-only GET /workers observability endpoint."""

import pytest
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.queue.worker_registry import WorkerRegistry
from app.repositories.worker_repository import WorkerRepository
from app.services.worker_service import WorkerService


@pytest.mark.asyncio
async def test_list_workers_requires_auth(client: AsyncClient) -> None:
    response = await client.get("/workers")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_workers_returns_registered_workers(
    client: AsyncClient, register_and_login, db_session: AsyncSession, redis_client: Redis
) -> None:
    user = await register_and_login()

    service = WorkerService(WorkerRepository(db_session), WorkerRegistry(redis_client))
    worker = await service.register(hostname="endpoint-test-worker", pid=9999, capacity=8)
    await db_session.commit()  # make it visible to the separate session the HTTP call opens

    response = await client.get("/workers", headers=user["headers"])

    assert response.status_code == 200
    by_id = {w["id"]: w for w in response.json()}
    assert str(worker.id) in by_id
    assert by_id[str(worker.id)]["is_alive"] is True
    assert by_id[str(worker.id)]["hostname"] == "endpoint-test-worker"