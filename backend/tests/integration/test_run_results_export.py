"""Integration tests for results export: GET /runs/{id}/results/export.

Unlike GET /runs/{id}/tasks (Part 2), which shows each task's single latest
result, export is built directly against request_results -- every attempt
gets its own row, so retry history is visible in the exported data rather
than collapsed to whatever happened last.
"""

import csv
import io
import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_request import ApiRequest
from app.models.enums import HttpMethod, TestRunStatus, TestRunType, TestTaskStatus
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask


async def _setup_run_with_results(
    db_session: AsyncSession, register_and_login, create_organization, client: AsyncClient
) -> dict:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Project"}, headers=owner["headers"]
    )
    assert project_response.status_code == 201
    collection_response = await client.post(
        f"/projects/{project_response.json()['id']}/collections",
        json={"name": "Collection"},
        headers=owner["headers"],
    )
    assert collection_response.status_code == 201
    collection_id = collection_response.json()["id"]

    api_request = ApiRequest(
        collection_id=collection_id, name="Login", method=HttpMethod.GET, url="https://example.com/login"
    )
    db_session.add(api_request)
    await db_session.flush()

    test_run = TestRun(
        collection_id=collection_id,
        initiated_by=uuid.UUID(owner["id"]),
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=2,
        config={"environment_variables": {}},
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(test_run)
    await db_session.flush()

    clean_task = TestTask(
        test_run_id=test_run.id, api_request_id=api_request.id, status=TestTaskStatus.COMPLETED
    )
    # Failed once, succeeded on retry -- two attempts, two request_results
    # rows, exactly the case export exists to surface.
    retried_task = TestTask(
        test_run_id=test_run.id,
        api_request_id=api_request.id,
        status=TestTaskStatus.COMPLETED,
        retry_count=1,
    )
    db_session.add_all([clean_task, retried_task])
    await db_session.flush()

    db_session.add(
        RequestResult(test_task_id=clean_task.id, attempt_number=1, status_code=200, latency_ms=30)
    )
    db_session.add(
        RequestResult(
            test_task_id=retried_task.id,
            attempt_number=1,
            status_code=500,
            latency_ms=15,
            error_message="server error",
        )
    )
    db_session.add(
        RequestResult(test_task_id=retried_task.id, attempt_number=2, status_code=200, latency_ms=28)
    )
    await db_session.commit()

    return {"owner": owner, "test_run": test_run, "clean_task": clean_task, "retried_task": retried_task}


@pytest.mark.asyncio
async def test_export_json_returns_all_attempts(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert len(response.json()) == 3  # 1 attempt for clean_task + 2 for retried_task


@pytest.mark.asyncio
async def test_export_shows_both_attempts_of_a_retried_task(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export", headers=ctx["owner"]["headers"]
    )

    retried_rows = sorted(
        (r for r in response.json() if r["test_task_id"] == str(ctx["retried_task"].id)),
        key=lambda r: r["attempt_number"],
    )

    assert [r["attempt_number"] for r in retried_rows] == [1, 2]
    assert [r["status_code"] for r in retried_rows] == [500, 200]


@pytest.mark.asyncio
async def test_export_json_is_the_default_format(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")


@pytest.mark.asyncio
async def test_export_csv_returns_parseable_csv_with_all_rows(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export?format=csv", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")

    reader = csv.DictReader(io.StringIO(response.text))
    rows = list(reader)
    assert len(rows) == 3
    assert "status_code" in reader.fieldnames
    assert "attempt_number" in reader.fieldnames


@pytest.mark.asyncio
async def test_export_sets_content_disposition_for_download(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    json_response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export", headers=ctx["owner"]["headers"]
    )
    csv_response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export?format=csv", headers=ctx["owner"]["headers"]
    )

    assert "attachment" in json_response.headers["content-disposition"]
    assert ".json" in json_response.headers["content-disposition"]
    assert "attachment" in csv_response.headers["content-disposition"]
    assert ".csv" in csv_response.headers["content-disposition"]


@pytest.mark.asyncio
async def test_export_returns_empty_for_run_with_no_results(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
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
    collection_id = collection_response.json()["id"]

    api_request = ApiRequest(
        collection_id=collection_id, name="Untouched", method=HttpMethod.GET, url="https://example.com"
    )
    db_session.add(api_request)
    await db_session.flush()

    test_run = TestRun(
        collection_id=collection_id,
        initiated_by=uuid.UUID(owner["id"]),
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=1,
        config={"environment_variables": {}},
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(test_run)
    await db_session.flush()
    db_session.add(
        TestTask(test_run_id=test_run.id, api_request_id=api_request.id, status=TestTaskStatus.PENDING)
    )
    await db_session.commit()

    json_response = await client.get(f"/runs/{test_run.id}/results/export", headers=owner["headers"])
    csv_response = await client.get(
        f"/runs/{test_run.id}/results/export?format=csv", headers=owner["headers"]
    )

    assert json_response.json() == []
    reader = csv.DictReader(io.StringIO(csv_response.text))
    assert list(reader) == []
    assert reader.fieldnames is not None  # header row still present, even with zero data rows


@pytest.mark.asyncio
async def test_export_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)
    outsider = await register_and_login()

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export", headers=outsider["headers"]
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_export_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/runs/{uuid.uuid4()}/results/export")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_export_rejects_invalid_format(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run_with_results(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/results/export?format=xml", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 422