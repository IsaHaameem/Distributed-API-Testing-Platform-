"""Integration tests for run orchestration -- the endpoint that actually
creates test_tasks and enqueues them onto the Redis Streams queue workers
consume from.

Each test runs against an isolated, unique-per-test stream (via the
autouse isolated_run_stream fixture below), not the real production stream
a running `worker` container consumes from. Earlier versions of this file
deliberately used the real stream, reasoning that's what orchestration
exists to feed -- but a real worker concurrently processing tasks these
tests create turned out to add genuine, uncoordinated Postgres load during
the full suite run, occasionally interfering with unrelated tests
elsewhere in the suite (confirmed: the full suite passes consistently with
the worker container stopped, and only intermittently otherwise). The
manual verification already done for Step 11 covers "a real worker
autonomously picks this up" -- these tests are about orchestration's own
correctness, not re-proving the pipeline Step 10 already tested end to end.
"""

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.queue.stream_client import StreamQueue
from app.routers.runs import get_task_stream_queue


@pytest_asyncio.fixture(autouse=True)
async def isolated_run_stream(redis_client: Redis):
    """Override get_task_stream_queue for the duration of each test in this
    file, redirecting run creation to a fresh, unique stream instead of the
    real one. Cleans up both the override and the stream's Redis key
    afterward, regardless of whether the test passed."""
    stream_name = f"test:orchestration:stream:{uuid.uuid4().hex[:12]}"
    group_name = f"test:orchestration:group:{uuid.uuid4().hex[:12]}"

    def override() -> StreamQueue:
        return StreamQueue(redis_client, stream_name, group_name)

    app.dependency_overrides[get_task_stream_queue] = override
    try:
        yield stream_name, group_name
    finally:
        app.dependency_overrides.pop(get_task_stream_queue, None)
        await redis_client.delete(stream_name)


async def _setup_collection_with_requests(
    client: AsyncClient, register_and_login, create_organization, request_count: int = 2
) -> dict:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Project"}, headers=owner["headers"]
    )
    collection_response = await client.post(
        f"/projects/{project_response.json()['id']}/collections",
        json={"name": "Collection"},
        headers=owner["headers"],
    )
    collection = collection_response.json()

    for i in range(request_count):
        await client.post(
            f"/collections/{collection['id']}/requests",
            json={"name": f"Request {i}", "method": "GET", "url": "https://example.com"},
            headers=owner["headers"],
        )

    return {"owner": owner, "org": org, "project": project_response.json(), "collection": collection}


@pytest.mark.asyncio
async def test_create_run_requires_auth(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection_with_requests(client, register_and_login, create_organization)

    response = await client.post(f"/collections/{ctx['collection']['id']}/runs", json={})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_run_fails_for_non_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection_with_requests(client, register_and_login, create_organization)
    outsider = await register_and_login()

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs", json={}, headers=outsider["headers"]
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_run_fails_for_collection_with_no_requests(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection_with_requests(
        client, register_and_login, create_organization, request_count=0
    )

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs", json={}, headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_run_creates_one_task_per_request_without_data_rows(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_collection_with_requests(
        client, register_and_login, create_organization, request_count=3
    )

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs", json={}, headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 202
    body = response.json()
    assert body["total_tasks"] == 3
    assert body["status"] == "running"
    assert "config" not in body

    tasks = (
        await db_session.execute(select(TestTask).where(TestTask.test_run_id == body["id"]))
    ).scalars().all()
    assert len(tasks) == 3
    assert all(t.data_row_index is None for t in tasks)


@pytest.mark.asyncio
async def test_create_run_creates_task_per_request_per_data_row(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_collection_with_requests(
        client, register_and_login, create_organization, request_count=2
    )
    data_rows = [{"userId": "1"}, {"userId": "2"}, {"userId": "3"}]

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs",
        json={"data_rows": data_rows},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 202
    assert response.json()["total_tasks"] == 6  # 2 requests x 3 rows

    tasks = (
        await db_session.execute(select(TestTask).where(TestTask.test_run_id == response.json()["id"]))
    ).scalars().all()
    row_indexes = sorted({t.data_row_index for t in tasks})
    assert row_indexes == [0, 1, 2]
    assert {t.data_context["userId"] for t in tasks if t.data_row_index == 1} == {"2"}


@pytest.mark.asyncio
async def test_create_run_rejects_empty_data_rows_list(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection_with_requests(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs",
        json={"data_rows": []},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_run_snapshots_environment_variables(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_collection_with_requests(client, register_and_login, create_organization)
    await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "baseUrl", "value": "https://api.example.com"},
        headers=ctx["owner"]["headers"],
    )
    await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "apiKey", "value": "sk-real-secret-value", "is_secret": True},
        headers=ctx["owner"]["headers"],
    )

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs", json={}, headers=ctx["owner"]["headers"]
    )

    test_run = (
        await db_session.execute(select(TestRun).where(TestRun.id == response.json()["id"]))
    ).scalar_one()

    env_vars = test_run.config["environment_variables"]
    assert env_vars["baseUrl"] == "https://api.example.com"
    # The DB-level snapshot must hold the real, unmasked value -- the worker
    # needs it to build real requests. Masking is an API-response-layer
    # concern (Step 8's EnvironmentVariableRead), not a storage-layer one.
    assert env_vars["apiKey"] == "sk-real-secret-value"


@pytest.mark.asyncio
async def test_create_run_enqueues_expected_number_of_tasks(
    client: AsyncClient,
    register_and_login,
    create_organization,
    redis_client: Redis,
    isolated_run_stream,
) -> None:
    stream_name, _group_name = isolated_run_stream
    ctx = await _setup_collection_with_requests(
        client, register_and_login, create_organization, request_count=4
    )

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/runs", json={}, headers=ctx["owner"]["headers"]
    )
    assert response.status_code == 202

    length = await redis_client.xlen(stream_name)
    assert length == 4