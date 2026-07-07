"""Integration test for the /health endpoint."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check_responds_with_expected_shape(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code in (200, 503)

    body = response.json()
    assert body["status"] in ("ok", "degraded")
    assert body["database"] in ("ok", "unavailable")
    assert body["redis"] in ("ok", "unavailable")