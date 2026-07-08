"""Unit tests for the HTTP executor, using httpx.MockTransport so no real
network calls happen."""

import json

import httpx
import pytest

from app.models.enums import HttpMethod
from worker.executor import Executor


def _client_with_handler(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_execute_returns_response_details_on_success() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok"}, headers={"X-Test": "yes"})

    executor = Executor(_client_with_handler(handler))

    result = await executor.execute(
        method=HttpMethod.GET,
        url="https://example.com/health",
        headers={},
        query_params={},
        body=None,
        timeout_ms=5000,
        chain_context={},
        environment_variables={},
    )

    assert result.status_code == 200
    assert result.error_message is None
    assert result.response_headers["x-test"] == "yes"
    assert json.loads(result.response_body) == {"status": "ok"}
    assert result.latency_ms >= 0


@pytest.mark.asyncio
async def test_execute_resolves_templates_before_sending() -> None:
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth_header"] = request.headers.get("authorization")
        return httpx.Response(200)

    executor = Executor(_client_with_handler(handler))

    await executor.execute(
        method=HttpMethod.GET,
        url="{{baseUrl}}/users",
        headers={"Authorization": "Bearer {{token}}"},
        query_params={},
        body=None,
        timeout_ms=5000,
        chain_context={"token": "abc123"},
        environment_variables={"baseUrl": "https://api.example.com"},
    )

    assert captured["url"] == "https://api.example.com/users"
    assert captured["auth_header"] == "Bearer abc123"


@pytest.mark.asyncio
async def test_execute_handles_undefined_variable_without_raising() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("should never be called")

    executor = Executor(_client_with_handler(handler))

    result = await executor.execute(
        method=HttpMethod.GET,
        url="{{missingVar}}/users",
        headers={},
        query_params={},
        body=None,
        timeout_ms=5000,
        chain_context={},
        environment_variables={},
    )

    assert result.status_code is None
    assert result.error_message is not None
    assert "missingVar" in result.error_message


@pytest.mark.asyncio
async def test_execute_handles_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("simulated timeout", request=request)

    executor = Executor(_client_with_handler(handler))

    result = await executor.execute(
        method=HttpMethod.GET,
        url="https://example.com/slow",
        headers={},
        query_params={},
        body=None,
        timeout_ms=1000,
        chain_context={},
        environment_variables={},
    )

    assert result.status_code is None
    assert result.succeeded is False
    assert "timed out" in result.error_message


@pytest.mark.asyncio
async def test_execute_handles_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("simulated connection failure", request=request)

    executor = Executor(_client_with_handler(handler))

    result = await executor.execute(
        method=HttpMethod.GET,
        url="https://example.com/unreachable",
        headers={},
        query_params={},
        body=None,
        timeout_ms=5000,
        chain_context={},
        environment_variables={},
    )

    assert result.status_code is None
    assert result.error_message is not None