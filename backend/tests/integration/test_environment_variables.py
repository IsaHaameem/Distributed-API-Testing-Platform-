"""Integration tests for environment variable endpoints."""

import pytest
from httpx import AsyncClient


async def _setup_project(client: AsyncClient, register_and_login, create_organization) -> dict:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Project"}, headers=owner["headers"]
    )
    return {"owner": owner, "org": org, "project": project_response.json()}


@pytest.mark.asyncio
async def test_create_non_secret_variable_succeeds_for_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )

    response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "baseUrl", "value": "https://api.example.com"},
        headers=member["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["key"] == "baseUrl"
    assert body["value"] == "https://api.example.com"
    assert body["is_secret"] is False


@pytest.mark.asyncio
async def test_create_secret_variable_masks_value_in_response(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)

    response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "apiKey", "value": "sk-super-secret-value", "is_secret": True},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["value"] == "********"
    assert "sk-super-secret-value" not in response.text


@pytest.mark.asyncio
async def test_member_cannot_create_secret_variable(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )

    response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "apiKey", "value": "secret", "is_secret": True},
        headers=member["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_create_variable_rejects_duplicate_key(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    payload = {"key": "duplicateKey", "value": "first"}

    first = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json=payload,
        headers=ctx["owner"]["headers"],
    )
    assert first.status_code == 201

    second = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "duplicateKey", "value": "second"},
        headers=ctx["owner"]["headers"],
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_variable_rejects_invalid_key_format(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)

    response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "not a valid key!", "value": "x"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_variables_masks_only_secrets(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]

    await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "plainVar", "value": "visible-value"},
        headers=headers,
    )
    await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "secretVar", "value": "hidden-value", "is_secret": True},
        headers=headers,
    )

    response = await client.get(
        f"/projects/{ctx['project']['id']}/environment-variables", headers=headers
    )

    assert response.status_code == 200
    by_key = {v["key"]: v for v in response.json()}
    assert by_key["plainVar"]["value"] == "visible-value"
    assert by_key["secretVar"]["value"] == "********"


@pytest.mark.asyncio
async def test_get_variable_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    outsider = await register_and_login()

    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "privateVar", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.get(f"/environment-variables/{variable_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_member_can_update_non_secret_value(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "baseUrl", "value": "https://old.example.com"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}",
        json={"value": "https://new.example.com"},
        headers=member["headers"],
    )

    assert response.status_code == 200
    assert response.json()["value"] == "https://new.example.com"


@pytest.mark.asyncio
async def test_member_cannot_update_secret_value(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "apiKey", "value": "original-secret", "is_secret": True},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}",
        json={"value": "attempted-overwrite"},
        headers=member["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_member_cannot_promote_variable_to_secret(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "wasPlain", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    assert create_response.status_code == 201, (
        f"Expected 201 creating the environment variable, got "
        f"{create_response.status_code}: {create_response.text}"
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}", json={"is_secret": True}, headers=member["headers"]
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_update_variable_rejects_explicit_null_value(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "someKey", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}", json={"value": None}, headers=ctx["owner"]["headers"]
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_owner_can_rename_variable(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "oldName", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}",
        json={"key": "newName"},
        headers=ctx["owner"]["headers"],
    )

    assert response.status_code == 200
    assert response.json()["key"] == "newName"


@pytest.mark.asyncio
async def test_rename_to_existing_key_fails(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]
    project_id = ctx["project"]["id"]

    await client.post(
        f"/projects/{project_id}/environment-variables",
        json={"key": "takenKey", "value": "x"},
        headers=headers,
    )
    create_response = await client.post(
        f"/projects/{project_id}/environment-variables",
        json={"key": "renameMe", "value": "y"},
        headers=headers,
    )
    variable_id = create_response.json()["id"]

    response = await client.patch(
        f"/environment-variables/{variable_id}", json={"key": "takenKey"}, headers=headers
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_member_cannot_delete_variable(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    member = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=ctx["owner"]["headers"],
    )
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "protectedVar", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    response = await client.delete(
        f"/environment-variables/{variable_id}", headers=member["headers"]
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_variable(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    admin = await register_and_login()
    await client.post(
        f"/organizations/{ctx['org']['id']}/members",
        json={"email": admin["email"], "role": "admin"},
        headers=ctx["owner"]["headers"],
    )
    create_response = await client.post(
        f"/projects/{ctx['project']['id']}/environment-variables",
        json={"key": "deletableVar", "value": "x"},
        headers=ctx["owner"]["headers"],
    )
    variable_id = create_response.json()["id"]

    delete_response = await client.delete(
        f"/environment-variables/{variable_id}", headers=admin["headers"]
    )
    assert delete_response.status_code == 204

    get_response = await client.get(
        f"/environment-variables/{variable_id}", headers=ctx["owner"]["headers"]
    )
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_deleting_project_cascades_to_its_environment_variables(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    ctx = await _setup_project(client, register_and_login, create_organization)
    headers = ctx["owner"]["headers"]
    project_id = ctx["project"]["id"]

    create_response = await client.post(
        f"/projects/{project_id}/environment-variables",
        json={"key": "orphanedVar", "value": "x"},
        headers=headers,
    )
    variable_id = create_response.json()["id"]

    delete_project_response = await client.delete(f"/projects/{project_id}", headers=headers)
    assert delete_project_response.status_code == 204

    get_variable_response = await client.get(
        f"/environment-variables/{variable_id}", headers=headers
    )
    assert get_variable_response.status_code == 404