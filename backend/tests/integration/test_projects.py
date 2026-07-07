"""Integration tests for project endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_project_succeeds_for_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])

    response = await client.post(
        f"/organizations/{org['id']}/projects",
        json={"name": "My Project", "description": "A test project"},
        headers=owner["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "My Project"
    assert body["description"] == "A test project"
    assert body["organization_id"] == org["id"]
    assert body["created_by"] == owner["id"]


@pytest.mark.asyncio
async def test_create_project_requires_auth(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])

    response = await client.post(f"/organizations/{org['id']}/projects", json={"name": "No Auth"})

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_project_fails_for_non_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    outsider = await register_and_login()
    org = await create_organization(owner["headers"])

    response = await client.post(
        f"/organizations/{org['id']}/projects",
        json={"name": "Should Fail"},
        headers=outsider["headers"],
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_projects_scoped_to_organization(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org_a = await create_organization(owner["headers"], name="Org A")
    org_b = await create_organization(owner["headers"], name="Org B")

    await client.post(f"/organizations/{org_a['id']}/projects", json={"name": "In A"}, headers=owner["headers"])
    await client.post(f"/organizations/{org_b['id']}/projects", json={"name": "In B"}, headers=owner["headers"])

    response = await client.get(f"/organizations/{org_a['id']}/projects", headers=owner["headers"])

    assert response.status_code == 200
    names = [p["name"] for p in response.json()]
    assert names == ["In A"]


@pytest.mark.asyncio
async def test_get_project_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    outsider = await register_and_login()
    org = await create_organization(owner["headers"])

    create_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Private"}, headers=owner["headers"]
    )
    project_id = create_response.json()["id"]

    response = await client.get(f"/projects/{project_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_member_can_update_project(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    member = await register_and_login()
    org = await create_organization(owner["headers"])

    await client.post(
        f"/organizations/{org['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )
    create_response = await client.post(
        f"/organizations/{org['id']}/projects",
        json={"name": "Original", "description": "Original description"},
        headers=owner["headers"],
    )
    project_id = create_response.json()["id"]

    response = await client.patch(
        f"/projects/{project_id}", json={"name": "Renamed"}, headers=member["headers"]
    )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "Renamed"
    assert body["description"] == "Original description"  # untouched field preserved


@pytest.mark.asyncio
async def test_update_project_can_clear_description(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])

    create_response = await client.post(
        f"/organizations/{org['id']}/projects",
        json={"name": "Has Description", "description": "Will be cleared"},
        headers=owner["headers"],
    )
    project_id = create_response.json()["id"]

    response = await client.patch(
        f"/projects/{project_id}", json={"description": None}, headers=owner["headers"]
    )

    assert response.status_code == 200
    assert response.json()["description"] is None


@pytest.mark.asyncio
async def test_member_cannot_delete_project(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    member = await register_and_login()
    org = await create_organization(owner["headers"])

    await client.post(
        f"/organizations/{org['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )
    create_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Protected"}, headers=owner["headers"]
    )
    project_id = create_response.json()["id"]

    response = await client.delete(f"/projects/{project_id}", headers=member["headers"])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_delete_project(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    admin = await register_and_login()
    org = await create_organization(owner["headers"])

    await client.post(
        f"/organizations/{org['id']}/members",
        json={"email": admin["email"], "role": "admin"},
        headers=owner["headers"],
    )
    create_response = await client.post(
        f"/organizations/{org['id']}/projects", json={"name": "Deletable"}, headers=owner["headers"]
    )
    project_id = create_response.json()["id"]

    delete_response = await client.delete(f"/projects/{project_id}", headers=admin["headers"])
    assert delete_response.status_code == 204

    get_response = await client.get(f"/projects/{project_id}", headers=owner["headers"])
    assert get_response.status_code == 404