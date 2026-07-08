"""Shared pytest fixtures."""

import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

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


@pytest_asyncio.fixture
async def create_organization(client: AsyncClient):
    """Factory fixture: create an organization owned by the given auth headers."""

    async def _create_organization(
        headers: dict, name: str = "Test Org", slug: str | None = None
    ) -> dict:
        slug = slug or f"org-{uuid.uuid4().hex[:12]}"
        response = await client.post(
            "/organizations", json={"name": name, "slug": slug}, headers=headers
        )
        return response.json()

    return _create_organization


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    """A Redis client for tests that talk to Redis directly (streams, worker liveness),
    bypassing HTTP the same way a worker process would."""
    from app.core.redis_client import get_redis_client

    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A raw session for tests that call repositories/services directly, bypassing
    HTTP. Commits are NOT automatic here -- call `await db_session.commit()`
    explicitly if a test needs its writes visible to a separate session (e.g.
    one an HTTP call within the same test will open via get_db)."""
    from app.database import AsyncSessionFactory

    async with AsyncSessionFactory() as session:
        try:
            yield session
        finally:
            await session.close()