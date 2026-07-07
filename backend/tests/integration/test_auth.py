"""Integration tests for authentication endpoints."""

import uuid

import pytest
from httpx import AsyncClient


def _unique_email() -> str:
    return f"test-{uuid.uuid4()}@example.com"


@pytest.mark.asyncio
async def test_register_creates_user(client: AsyncClient) -> None:
    email = _unique_email()

    response = await client.post(
        "/auth/register",
        json={"email": email, "password": "a-strong-password-123", "full_name": "Test User"},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == email
    assert body["full_name"] == "Test User"
    assert body["is_active"] is True
    assert "id" in body
    assert "password" not in body
    assert "hashed_password" not in body


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client: AsyncClient) -> None:
    email = _unique_email()
    payload = {"email": email, "password": "a-strong-password-123", "full_name": "Test User"}

    first = await client.post("/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_register_weak_password_fails(client: AsyncClient) -> None:
    response = await client.post(
        "/auth/register",
        json={"email": _unique_email(), "password": "short", "full_name": "Test User"},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient) -> None:
    email = _unique_email()
    password = "a-strong-password-123"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )

    response = await client.post("/auth/login", data={"username": email, "password": password})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert len(body["access_token"]) > 0


@pytest.mark.asyncio
async def test_login_rejects_wrong_password_and_unknown_email_identically(
    client: AsyncClient,
) -> None:
    email = _unique_email()
    await client.post(
        "/auth/register",
        json={"email": email, "password": "a-strong-password-123", "full_name": "Test User"},
    )

    wrong_password = await client.post(
        "/auth/login", data={"username": email, "password": "not-the-password"}
    )
    unknown_email = await client.post(
        "/auth/login", data={"username": _unique_email(), "password": "whatever-password"}
    )

    assert wrong_password.status_code == 401
    assert unknown_email.status_code == 401
    assert wrong_password.json()["detail"] == unknown_email.json()["detail"]


@pytest.mark.asyncio
async def test_me_requires_token(client: AsyncClient) -> None:
    response = await client.get("/auth/me")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_me_returns_current_user(client: AsyncClient) -> None:
    email = _unique_email()
    password = "a-strong-password-123"
    await client.post(
        "/auth/register",
        json={"email": email, "password": password, "full_name": "Test User"},
    )
    login_response = await client.post(
        "/auth/login", data={"username": email, "password": password}
    )
    access_token = login_response.json()["access_token"]

    response = await client.get("/auth/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    assert response.json()["email"] == email