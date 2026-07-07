"""Integration tests for API request endpoints."""

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
async def test_create_request_succeeds_with_defaults(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Get user", "method": "GET", "url": "{{baseUrl}}/users/1"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["method"] == "GET"
    assert body["order_index"] == 0
    assert body["timeout_ms"] == 30000
    assert body["headers"] == {}
    assert body["extract_rules"] == []


@pytest.mark.asyncio
async def test_create_request_auto_increments_order_index(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    collection_id = ctx["collection"]["id"]
    headers = ctx["owner"]["headers"]

    first = await client.post(
        f"/collections/{collection_id}/requests",
        json={"name": "First", "method": "GET", "url": "{{baseUrl}}/a"},
        headers=headers,
    )
    second = await client.post(
        f"/collections/{collection_id}/requests",
        json={"name": "Second", "method": "GET", "url": "{{baseUrl}}/b"},
        headers=headers,
    )

    assert first.json()["order_index"] == 0
    assert second.json()["order_index"] == 1


@pytest.mark.asyncio
async def test_create_request_respects_explicit_order_index(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Pinned", "method": "GET", "url": "{{baseUrl}}/x", "order_index": 5},
        headers=ctx["owner"]["headers"],
    )

    assert response.json()["order_index"] == 5


@pytest.mark.asyncio
async def test_create_request_with_valid_extract_rules(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={
            "name": "Login",
            "method": "POST",
            "url": "{{baseUrl}}/login",
            "extract_rules": [
                {"type": "json_path", "path": "$.data.token", "save_as": "authToken"},
                {"type": "jwt_claim", "source_var": "authToken", "claim": "sub", "save_as": "userId"},
            ],
        },
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    rules = response.json()["extract_rules"]
    assert len(rules) == 2
    assert rules[0]["save_as"] == "authToken"
    assert rules[1]["claim"] == "sub"


@pytest.mark.asyncio
async def test_create_request_rejects_unknown_extract_rule_type(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={
            "name": "Bad rule",
            "method": "GET",
            "url": "{{baseUrl}}/x",
            "extract_rules": [{"type": "xpath", "path": "//token", "save_as": "x"}],
        },
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_request_rejects_jsonpath_without_dollar_prefix(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={
            "name": "Bad path",
            "method": "GET",
            "url": "{{baseUrl}}/x",
            "extract_rules": [{"type": "json_path", "path": "data.token", "save_as": "x"}],
        },
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_get_request_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)
    outsider = await register_and_login()

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Private", "method": "GET", "url": "{{baseUrl}}/x"},
        headers=ctx["owner"]["headers"],
    )
    request_id = create_response.json()["id"]

    response = await client.get(f"/requests/{request_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_update_request_rejects_explicit_null_for_required_field(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    """Regression test for the same null-vs-omitted gap fixed in organizations/projects/collections."""
    ctx = await _setup_collection(client, register_and_login, create_organization)

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Original", "method": "GET", "url": "{{baseUrl}}/x"},
        headers=ctx["owner"]["headers"],
    )
    request_id = create_response.json()["id"]

    response = await client.patch(
        f"/requests/{request_id}", json={"name": None}, headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_update_request_can_clear_body(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_collection(client, register_and_login, create_organization)

    create_response = await client.post(
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Has body", "method": "POST", "url": "{{baseUrl}}/x", "body": '{"a": 1}'},
        headers=ctx["owner"]["headers"],
    )
    request_id = create_response.json()["id"]

    response = await client.patch(
        f"/requests/{request_id}", json={"body": None}, headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 200
    assert response.json()["body"] is None


@pytest.mark.asyncio
async def test_member_cannot_delete_request(
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
        f"/collections/{ctx['collection']['id']}/requests",
        json={"name": "Protected", "method": "GET", "url": "{{baseUrl}}/x"},
        headers=ctx["owner"]["headers"],
    )
    request_id = create_response.json()["id"]

    response = await client.delete(f"/requests/{request_id}", headers=member["headers"])

    assert response.status_code == 403