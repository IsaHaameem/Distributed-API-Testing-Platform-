"""Integration tests for reading run and task state: GET /collections/{id}/runs,
GET /runs/{id}, GET /runs/{id}/tasks.

Run/task creation is test_run_orchestration.py's job; this file is about
reading state back out, so scenarios are built directly against the models
rather than via a real POST .../runs plus a running worker -- deterministic
control over exactly which statuses and results exist, with no dependency
on Redis Streams or worker timing at all.
"""

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_request import ApiRequest
from app.models.enums import HttpMethod, LogLevel, TestRunStatus, TestRunType, TestTaskStatus
from app.models.execution_log import ExecutionLog
from app.models.request_result import RequestResult
from app.models.test_run import TestRun
from app.models.test_task import TestTask
from app.models.user import User


async def _setup_run(
    db_session: AsyncSession, register_and_login, create_organization, client: AsyncClient
) -> dict:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Project"}, headers=owner["headers"]
    )
    assert project_response.status_code == 201, (
        f"Expected 201 creating the project, got {project_response.status_code}: {project_response.text}"
    )
    collection_response = await client.post(
        f"/projects/{project_response.json()['id']}/collections",
        json={"name": "Collection"},
        headers=owner["headers"],
    )
    assert collection_response.status_code == 201, (
        f"Expected 201 creating the collection, got {collection_response.status_code}: "
        f"{collection_response.text}"
    )
    collection_id = collection_response.json()["id"]

    api_request = ApiRequest(
        collection_id=collection_id, name="Request", method=HttpMethod.GET, url="https://example.com"
    )
    db_session.add(api_request)
    await db_session.flush()

    test_run = TestRun(
        collection_id=collection_id,
        initiated_by=uuid.UUID(owner["id"]),
        status=TestRunStatus.RUNNING,
        run_type=TestRunType.MANUAL,
        total_tasks=3,
        config={"environment_variables": {}},
        started_at=datetime.now(timezone.utc),
    )
    db_session.add(test_run)
    await db_session.flush()

    completed_task = TestTask(
        test_run_id=test_run.id, api_request_id=api_request.id, status=TestTaskStatus.COMPLETED
    )
    failed_task = TestTask(
        test_run_id=test_run.id, api_request_id=api_request.id, status=TestTaskStatus.FAILED
    )
    pending_task = TestTask(
        test_run_id=test_run.id, api_request_id=api_request.id, status=TestTaskStatus.PENDING
    )
    db_session.add_all([completed_task, failed_task, pending_task])
    await db_session.flush()

    db_session.add(
        RequestResult(test_task_id=completed_task.id, attempt_number=1, status_code=200, latency_ms=42)
    )
    db_session.add(
        RequestResult(
            test_task_id=failed_task.id,
            attempt_number=1,
            status_code=500,
            latency_ms=10,
            error_message="server error",
        )
    )
    await db_session.commit()

    return {
        "owner": owner,
        "collection_id": collection_id,
        "test_run": test_run,
        "completed_task": completed_task,
        "failed_task": failed_task,
        "pending_task": pending_task,
    }


@pytest.mark.asyncio
async def test_list_runs_returns_runs_for_collection(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/collections/{ctx['collection_id']}/runs", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    run_ids = [r["id"] for r in response.json()]
    assert str(ctx["test_run"].id) in run_ids


@pytest.mark.asyncio
async def test_list_runs_filters_by_status(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    running_response = await client.get(
        f"/collections/{ctx['collection_id']}/runs?status=running", headers=ctx["owner"]["headers"]
    )
    completed_response = await client.get(
        f"/collections/{ctx['collection_id']}/runs?status=completed", headers=ctx["owner"]["headers"]
    )

    assert str(ctx["test_run"].id) in [r["id"] for r in running_response.json()]
    assert str(ctx["test_run"].id) not in [r["id"] for r in completed_response.json()]


@pytest.mark.asyncio
async def test_list_runs_scoped_to_collection(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx_a = await _setup_run(db_session, register_and_login, create_organization, client)
    ctx_b = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/collections/{ctx_a['collection_id']}/runs", headers=ctx_a["owner"]["headers"]
    )

    run_ids = [r["id"] for r in response.json()]
    assert str(ctx_a["test_run"].id) in run_ids
    assert str(ctx_b["test_run"].id) not in run_ids


@pytest.mark.asyncio
async def test_list_runs_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/collections/{uuid.uuid4()}/runs")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_runs_fails_for_non_member(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    outsider = await register_and_login()

    response = await client.get(
        f"/collections/{ctx['collection_id']}/runs", headers=outsider["headers"]
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_run_returns_run_detail(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(f"/runs/{ctx['test_run'].id}", headers=ctx["owner"]["headers"])

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ctx["test_run"].id)
    assert body["total_tasks"] == 3
    assert "config" not in body


@pytest.mark.asyncio
async def test_get_run_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    outsider = await register_and_login()

    response = await client.get(f"/runs/{ctx['test_run'].id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_run_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/runs/{uuid.uuid4()}")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_list_tasks_includes_latest_result(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    by_id = {t["id"]: t for t in response.json()["tasks"]}
    failed = by_id[str(ctx["failed_task"].id)]
    assert failed["status"] == "failed"
    assert failed["latest_result"]["status_code"] == 500
    assert failed["latest_result"]["error_message"] == "server error"


@pytest.mark.asyncio
async def test_list_tasks_returns_null_result_for_pending_task(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks", headers=ctx["owner"]["headers"]
    )

    by_id = {t["id"]: t for t in response.json()["tasks"]}
    assert by_id[str(ctx["pending_task"].id)]["latest_result"] is None


@pytest.mark.asyncio
async def test_list_tasks_filters_by_status(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks?status=failed", headers=ctx["owner"]["headers"]
    )

    body = response.json()
    assert body["total"] == 1
    assert body["tasks"][0]["id"] == str(ctx["failed_task"].id)


@pytest.mark.asyncio
async def test_list_tasks_respects_limit_and_offset(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks?limit=1&offset=1", headers=ctx["owner"]["headers"]
    )

    body = response.json()
    assert body["total"] == 3
    assert body["limit"] == 1
    assert body["offset"] == 1
    assert len(body["tasks"]) == 1


@pytest.mark.asyncio
async def test_list_tasks_picks_the_most_recent_attempt_when_multiple_exist(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    db_session.add(
        RequestResult(
            test_task_id=ctx["failed_task"].id, attempt_number=2, status_code=200, latency_ms=15
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks", headers=ctx["owner"]["headers"]
    )

    by_id = {t["id"]: t for t in response.json()["tasks"]}
    assert by_id[str(ctx["failed_task"].id)]["latest_result"]["status_code"] == 200


@pytest.mark.asyncio
async def test_list_tasks_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    outsider = await register_and_login()

    response = await client.get(f"/runs/{ctx['test_run'].id}/tasks", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_tasks_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/runs/{uuid.uuid4()}/tasks")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_get_task_detail_returns_full_attempt_history_including_body_and_headers(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    # failed_task already has one attempt from _setup_run (attempt_number=1,
    # status_code=500, no headers/body); add a second attempt with a full
    # response, to prove the detail view returns EVERY attempt, not just the
    # latest -- and that headers/body, hidden from the list view, are here.
    db_session.add(
        RequestResult(
            test_task_id=ctx["failed_task"].id,
            attempt_number=2,
            status_code=200,
            latency_ms=15,
            response_headers={"content-type": "application/json"},
            response_body_snippet='{"ok": true}',
            assertions_passed=True,
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks/{ctx['failed_task'].id}", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(ctx["failed_task"].id)
    assert len(body["attempts"]) == 2
    assert [a["attempt_number"] for a in body["attempts"]] == [1, 2]

    first_attempt, second_attempt = body["attempts"]
    assert first_attempt["status_code"] == 500
    assert first_attempt["error_message"] == "server error"
    assert first_attempt["response_headers"] is None  # not set in _setup_run

    assert second_attempt["status_code"] == 200
    assert second_attempt["response_headers"] == {"content-type": "application/json"}
    assert second_attempt["response_body_snippet"] == '{"ok": true}'
    assert second_attempt["assertions_passed"] is True


@pytest.mark.asyncio
async def test_get_task_detail_includes_execution_logs_in_order(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    db_session.add(
        ExecutionLog(
            test_run_id=ctx["test_run"].id,
            test_task_id=ctx["failed_task"].id,
            level=LogLevel.WARNING,
            message="Attempt 1 failed, will retry: server error",
        )
    )
    db_session.add(
        ExecutionLog(
            test_run_id=ctx["test_run"].id,
            test_task_id=ctx["failed_task"].id,
            level=LogLevel.ERROR,
            message="Task failed permanently after 1 attempt(s): server error",
        )
    )
    await db_session.commit()

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks/{ctx['failed_task'].id}", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    logs = response.json()["logs"]
    assert len(logs) == 2
    assert logs[0]["level"] == "warning"
    assert logs[1]["level"] == "error"


@pytest.mark.asyncio
async def test_get_task_detail_returns_empty_lists_for_a_task_with_no_attempts_or_logs(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks/{ctx['pending_task'].id}", headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    body = response.json()
    assert body["attempts"] == []
    assert body["logs"] == []


@pytest.mark.asyncio
async def test_get_task_detail_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx = await _setup_run(db_session, register_and_login, create_organization, client)
    outsider = await register_and_login()

    response = await client.get(
        f"/runs/{ctx['test_run'].id}/tasks/{ctx['failed_task'].id}", headers=outsider["headers"]
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task_detail_404s_for_a_task_belonging_to_a_different_run(
    client: AsyncClient, register_and_login, create_organization, db_session: AsyncSession
) -> None:
    ctx_a = await _setup_run(db_session, register_and_login, create_organization, client)
    ctx_b = await _setup_run(db_session, register_and_login, create_organization, client)

    # ctx_a's owner is a member of ctx_a's org, so a plain non-member 404
    # wouldn't distinguish "wrong run" from "no access" -- this specifically
    # proves a task genuinely belonging to a DIFFERENT run 404s under a run
    # it doesn't belong to, even for someone who could see that other run.
    response = await client.get(
        f"/runs/{ctx_a['test_run'].id}/tasks/{ctx_b['failed_task'].id}",
        headers=ctx_a["owner"]["headers"],
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_task_detail_requires_auth(client: AsyncClient) -> None:
    response = await client.get(f"/runs/{uuid.uuid4()}/tasks/{uuid.uuid4()}")
    assert response.status_code == 401