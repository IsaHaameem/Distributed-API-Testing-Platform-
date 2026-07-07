"""Integration tests for collection endpoints."""

import pytest
from httpx import AsyncClient


async def _create_project(client: AsyncClient, headers: dict, org_id: str, name: str = "Test Project") -> dict:
    response = await client.post(
        f"/organizations/{org_id}/projects", json={"name": name}, headers=headers
    )
    return response.json()


@pytest.mark.asyncio
async def test_create_collection_succeeds(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    response = await client.post(
        f"/projects/{project['id']}/collections",
        json={"name": "Smoke Tests", "description": "Basic checks"},
        headers=owner["headers"],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Smoke Tests"
    assert body["project_id"] == project["id"]


@pytest.mark.asyncio
async def test_create_collection_fails_for_non_member(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    outsider = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    response = await client.post(
        f"/projects/{project['id']}/collections",
        json={"name": "Should Fail"},
        headers=outsider["headers"],
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_collections_scoped_to_project(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project_a = await _create_project(client, owner["headers"], org["id"], name="Project A")
    project_b = await _create_project(client, owner["headers"], org["id"], name="Project B")

    await client.post(
        f"/projects/{project_a['id']}/collections", json={"name": "In A"}, headers=owner["headers"]
    )
    await client.post(
        f"/projects/{project_b['id']}/collections", json={"name": "In B"}, headers=owner["headers"]
    )

    response = await client.get(f"/projects/{project_a['id']}/collections", headers=owner["headers"])

    assert response.status_code == 200
    names = [c["name"] for c in response.json()]
    assert names == ["In A"]


@pytest.mark.asyncio
async def test_get_collection_hides_existence_from_non_members(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    outsider = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    create_response = await client.post(
        f"/projects/{project['id']}/collections", json={"name": "Private"}, headers=owner["headers"]
    )
    collection_id = create_response.json()["id"]

    response = await client.get(f"/collections/{collection_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_member_can_update_collection(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    member = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    await client.post(
        f"/organizations/{org['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )
    create_response = await client.post(
        f"/projects/{project['id']}/collections", json={"name": "Original"}, headers=owner["headers"]
    )
    collection_id = create_response.json()["id"]

    response = await client.patch(
        f"/collections/{collection_id}", json={"name": "Renamed"}, headers=member["headers"]
    )

    assert response.status_code == 200
    assert response.json()["name"] == "Renamed"


@pytest.mark.asyncio
async def test_member_cannot_delete_collection(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    member = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    await client.post(
        f"/organizations/{org['id']}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )
    create_response = await client.post(
        f"/projects/{project['id']}/collections", json={"name": "Protected"}, headers=owner["headers"]
    )
    collection_id = create_response.json()["id"]

    response = await client.delete(f"/collections/{collection_id}", headers=member["headers"])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_delete_collection(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    create_response = await client.post(
        f"/projects/{project['id']}/collections", json={"name": "Deletable"}, headers=owner["headers"]
    )
    collection_id = create_response.json()["id"]

    delete_response = await client.delete(f"/collections/{collection_id}", headers=owner["headers"])
    assert delete_response.status_code == 204

    get_response = await client.get(f"/collections/{collection_id}", headers=owner["headers"])
    assert get_response.status_code == 404


@pytest.mark.asyncio
async def test_deleting_project_cascades_to_its_collections(
    client: AsyncClient, register_and_login, create_organization
) -> None:
    """Verifies the ondelete=CASCADE FK from Step 3 actually behaves as designed."""
    owner = await register_and_login()
    org = await create_organization(owner["headers"])
    project = await _create_project(client, owner["headers"], org["id"])

    create_response = await client.post(
        f"/projects/{project['id']}/collections", json={"name": "Orphaned Soon"}, headers=owner["headers"]
    )
    collection_id = create_response.json()["id"]

    delete_project_response = await client.delete(f"/projects/{project['id']}", headers=owner["headers"])
    assert delete_project_response.status_code == 204

    get_collection_response = await client.get(f"/collections/{collection_id}", headers=owner["headers"])
    assert get_collection_response.status_code == 404