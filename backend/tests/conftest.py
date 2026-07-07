"""Shared pytest fixtures."""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app


@pytest_asyncio.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """An async HTTP client wired directly to the FastAPI app (no real network)."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture
async def register_and_login(client: AsyncClient):
    """Factory fixture: register + log in a fresh user, return their id/email/auth headers."""

    async def _register_and_login(
        email: str | None = None,
        password: str = "a-strong-password-123",
        full_name: str = "Test User",
    ) -> dict:
        email = email or f"test-{uuid.uuid4()}@example.com"
        register_response = await client.post(
            "/auth/register",
            json={"email": email, "password": password, "full_name": full_name},
        )
        user_id = register_response.json()["id"]

        login_response = await client.post(
            "/auth/login", data={"username": email, "password": password}
        )
        token = login_response.json()["access_token"]

        return {
            "id": user_id,
            "email": email,
            "token": token,
            "headers": {"Authorization": f"Bearer {token}"},
        }

    return _register_and_login