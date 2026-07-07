"""Integration tests for schedule endpoints."""

import pytest
from httpx import AsyncClient


async def _setup_collection(client: AsyncClient, register_and_login, create_organization) -> dict:
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
    return {"owner": owner, "org": org, "collection": collection_response.json()}


@pytest.mark.asyncio
async def test_create_schedule_computes_next_run_at(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["cron_expression"] == "0 9 * * *"
    assert body["timezone"] == "UTC"
    assert body["is_active"] is True
    assert body["next_run_at"] is not None
    assert body["last_run_at"] is None


@pytest.mark.asyncio
async def test_create_inactive_schedule_has_no_next_run_at(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *", "is_active": False},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    assert response.json()["next_run_at"] is None


@pytest.mark.asyncio
async def test_create_schedule_accepts_explicit_timezone(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *", "timezone": "Asia/Kolkata"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["timezone"] == "Asia/Kolkata"
    assert body["next_run_at"] is not None


@pytest.mark.asyncio
async def test_create_schedule_rejects_invalid_cron_expression(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "not a cron expression"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_schedule_rejects_invalid_timezone(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *", "timezone": "Not/A/Real/Zone"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_schedule_fails_for_non_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    outsider = await register_and_login()

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=outsider["headers"],
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_schedule_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    outsider = await register_and_login()

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=ctx["owner"]["headers"],
    )
    schedule_id = create_response.json()["id"]

    response = await client.get(f"/schedules/{schedule_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_schedule_recomputes_next_run_at_on_cron_change(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "* * * * *"},  # every minute
        headers=headers,
    )
    schedule_id = create_response.json()["id"]
    original_next_run_at = create_response.json()["next_run_at"]

    response = await client.patch(
        f"/schedules/{schedule_id}",
        json={"cron_expression": "0 0 1 1 *"},  # once a year
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json()["next_run_at"] != original_next_run_at


@pytest.mark.asyncio
async def test_deactivating_schedule_clears_next_run_at(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=headers,
    )
    schedule_id = create_response.json()["id"]
    assert create_response.json()["next_run_at"] is not None

    response = await client.patch(
        f"/schedules/{schedule_id}", json={"is_active": False}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["is_active"] is False
    assert response.json()["next_run_at"] is None


@pytest.mark.asyncio
async def test_reactivating_schedule_recomputes_next_run_at(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *", "is_active": False},
        headers=headers,
    )
    schedule_id = create_response.json()["id"]

    response = await client.patch(
        f"/schedules/{schedule_id}", json={"is_active": True}, headers=headers
    )

    assert response.status_code == 200
    assert response.json()["next_run_at"] is not None


@pytest.mark.asyncio
async def test_update_schedule_rejects_explicit_null_cron_expression(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=headers,
    )
    schedule_id = create_response.json()["id"]

    response = await client.patch(
        f"/schedules/{schedule_id}", json={"cron_expression": None}, headers=headers
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_member_cannot_delete_schedule(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=ctx["owner"]["headers"],
    )
    schedule_id = create_response.json()["id"]

    response = await client.delete(f"/schedules/{schedule_id}", headers=member["headers"])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_schedule(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    admin = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": admin["email"], "role": "admin"},
        headers=ctx["owner"]["headers"],
    )

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=ctx["owner"]["headers"],
    )
    schedule_id = create_response.json()["id"]

    delete_response = await client.delete(f"/schedules/{schedule_id}", headers=admin["headers"])
    assert delete_response.status_code == 204

    get_response = await client.get(f"/schedules/{schedule_id}", headers=ctx["owner"]["headers"])
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_deleting_collection_cascades_to_its_schedules(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]
    collection_id = ctx["collection"]["id"]

    create_response = await client.post(
        f"/collections/{collection_id}/schedules",
        json={"cron_expression": "0 9 * * *"},
        headers=headers,
    )
    schedule_id = create_response.json()["id"]

    delete_collection_response = await client.delete(f"/collections/{collection_id}", headers=headers)
    assert delete_collection_response.status_code == 204

    get_schedule_response = await client.get(f"/schedules/{schedule_id}", headers=headers)
    assert get_schedule_response.status_code == 404