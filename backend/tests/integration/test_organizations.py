"""Integration tests for organization and membership endpoints."""

import uuid

import pytest
from httpx import AsyncClient


def _unique_slug() -> str:
    return f"org-{uuid.uuid4().hex[:12]}"


@pytest.mark.asyncio
async def test_create_organization_succeeds(client: AsyncClient, register_and_login) -> None:
    user = await register_and_login()
    slug = _unique_slug()

    response = await client.post(
        "/organizations", json={"name": "Acme Corp", "slug": slug}, headers=user["headers"]
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "Acme Corp"
    assert body["slug"] == slug
    assert body["my_role"] == "owner"


@pytest.mark.asyncio
async def test_create_organization_requires_auth(client: AsyncClient) -> None:
    response = await client.post(
        "/organizations", json={"name": "No Auth", "slug": _unique_slug()}
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_create_organization_duplicate_slug_fails(
    client: AsyncClient, register_and_login
) -> None:
    user = await register_and_login()
    slug = _unique_slug()

    first = await client.post(
        "/organizations", json={"name": "First", "slug": slug}, headers=user["headers"]
    )
    assert first.status_code == 201

    second = await client.post(
        "/organizations", json={"name": "Second", "slug": slug}, headers=user["headers"]
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_create_organization_rejects_invalid_slug(
    client: AsyncClient, register_and_login
) -> None:
    user = await register_and_login()

    response = await client.post(
        "/organizations",
        json={"name": "Bad Slug", "slug": "Not A Valid Slug!"},
        headers=user["headers"],
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_organizations_returns_only_my_orgs(
    client: AsyncClient, register_and_login
) -> None:
    user_a = await register_and_login()
    user_b = await register_and_login()

    await client.post(
        "/organizations", json={"name": "A's Org", "slug": _unique_slug()}, headers=user_a["headers"]
    )

    response = await client.get("/organizations", headers=user_b["headers"])

    assert response.status_code == 200
    names = [org["name"] for org in response.json()]
    assert "A's Org" not in names


@pytest.mark.asyncio
async def test_get_organization_hides_existence_from_non_members(
    client: AsyncClient, register_and_login
) -> None:
    owner = await register_and_login()
    outsider = await register_and_login()

    create_response = await client.post(
        "/organizations",
        json={"name": "Private Org", "slug": _unique_slug()},
        headers=owner["headers"],
    )
    org_id = create_response.json()["id"]

    response = await client.get(f"/organizations/{org_id}", headers=outsider["headers"])

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_list_members_includes_owner(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    response = await client.get(f"/organizations/{org_id}/members", headers=owner["headers"])

    assert response.status_code == 200
    members = response.json()
    assert len(members) == 1
    assert members[0]["email"] == owner["email"]
    assert members[0]["role"] == "owner"


@pytest.mark.asyncio
async def test_member_cannot_update_organization(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()
    member = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )

    response = await client.patch(
        f"/organizations/{org_id}", json={"name": "Renamed"}, headers=member["headers"]
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_admin_cannot_delete_organization(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()
    admin = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": admin["email"], "role": "admin"},
        headers=owner["headers"],
    )

    response = await client.delete(f"/organizations/{org_id}", headers=admin["headers"])

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_delete_organization(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    response = await client.delete(f"/organizations/{org_id}", headers=owner["headers"])

    assert response.status_code == 204


@pytest.mark.asyncio
async def test_add_member_with_unknown_email_fails(
    client: AsyncClient, register_and_login
) -> None:
    owner = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    response = await client.post(
        f"/organizations/{org_id}/members",
        json={"email": f"{_unique_slug()}@example.com", "role": "member"},
        headers=owner["headers"],
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_admin_cannot_add_member_as_owner(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()
    admin = await register_and_login()
    target = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": admin["email"], "role": "admin"},
        headers=owner["headers"],
    )

    response = await client.post(
        f"/organizations/{org_id}/members",
        json={"email": target["email"], "role": "owner"},
        headers=admin["headers"],
    )

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_owner_can_promote_member_to_admin(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()
    member = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )

    response = await client.patch(
        f"/organizations/{org_id}/members/{member['id']}",
        json={"role": "admin"},
        headers=owner["headers"],
    )

    assert response.status_code == 200
    assert response.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_sole_owner_cannot_leave(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    response = await client.delete(
        f"/organizations/{org_id}/members/{owner['id']}", headers=owner["headers"]
    )

    assert response.status_code == 409


@pytest.mark.asyncio
async def test_member_can_remove_self(client: AsyncClient, register_and_login) -> None:
    owner = await register_and_login()
    member = await register_and_login()

    create_response = await client.post(
        "/organizations", json={"name": "Org", "slug": _unique_slug()}, headers=owner["headers"]
    )
    org_id = create_response.json()["id"]

    await client.post(
        f"/organizations/{org_id}/members",
        json={"email": member["email"], "role": "member"},
        headers=owner["headers"],
    )

    response = await client.delete(
        f"/organizations/{org_id}/members/{member['id']}", headers=member["headers"]
    )

    assert response.status_code == 204