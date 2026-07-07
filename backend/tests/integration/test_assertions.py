"""Integration tests for assertion endpoints."""

import pytest
from httpx import AsyncClient


async def _setup_request(client: AsyncClient, register_and_login, create_organization) -> dict:
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
    request_response = await client.post(
        f"/collections/{collection_response.json()['id']}/requests",
        json={"name": "Request", "method": "GET", "url": "{{baseUrl}}/x"},
        headers=owner["headers"],
    )
    return {"owner": owner, "request": request_response.json()}


@pytest.mark.asyncio
async def test_create_status_code_assertion(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)

    response = await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "status_code_equals", "config": {"expected": 200}},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "status_code_equals"
    assert body["config"]["expected"] == 200


@pytest.mark.asyncio
async def test_create_json_path_assertion(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)

    response = await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "json_path_equals", "config": {"path": "$.status", "expected": "ok"}},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    assert response.json()["config"] == {"path": "$.status", "expected": "ok"}


@pytest.mark.asyncio
async def test_create_assertion_rejects_config_mismatched_with_type(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)

    response = await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "status_code_equals", "config": {"expected": "not-a-number"}},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_assertion_rejects_unknown_type(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)

    response = await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "body_contains", "config": {"value": "ok"}},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_assertions_returns_all_for_request(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "status_code_equals", "config": {"expected": 200}},
        headers=headers,
    )
    await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "response_time_below", "config": {"max_ms": 500}},
        headers=headers,
    )

    response = await client.get(f"/requests/{ctx['request']['id']}/assertions", headers=headers)

    assert response.status_code == 200
    assert len(response.json()) == 2


@pytest.mark.asyncio
async def test_delete_assertion_succeeds(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    create_response = await client.post(
        f"/requests/{ctx['request']['id']}/assertions",
        json={"type": "status_code_equals", "config": {"expected": 200}},
        headers=headers,
    )
    assertion_id = create_response.json()["id"]

    delete_response = await client.delete(f"/assertions/{assertion_id}", headers=headers)
    assert delete_response.status_code == 204

    list_response = await client.get(f"/requests/{ctx['request']['id']}/assertions", headers=headers)
    assert list_response.json() == []


@pytest.mark.asyncio
async def test_deleting_request_cascades_to_its_assertions(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_request(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]
    request_id = ctx["request"]["id"]

    create_response = await client.post(
        f"/requests/{request_id}/assertions",
        json={"type": "status_code_equals", "config": {"expected": 200}},
        headers=headers,
    )
    assertion_id = create_response.json()["id"]

    delete_request_response = await client.delete(f"/requests/{request_id}", headers=headers)
    assert delete_request_response.status_code == 204

    get_assertion_response = await client.delete(f"/assertions/{assertion_id}", headers=headers)
    assert get_assertion_response.status_code == 404