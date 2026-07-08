"""HTTP execution engine: resolves a request template against context, then
executes it via a shared, connection-pooled httpx.AsyncClient.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx

from app.models.enums import HttpMethod
from worker.template_resolver import UndefinedVariableError, resolve_mapping, resolve_template


@dataclass
class ExecutionResult:
    status_code: int | None
    latency_ms: int
    response_headers: dict[str, str] | None
    response_body: str | None
    error_message: str | None

    @property
    def succeeded(self) -> bool:
        """A request "succeeded" at the transport level if it got a response at
        all -- a 500 from the target API is still a successful execution as far
        as the platform is concerned; assertions decide whether THAT'S a pass."""
        return self.error_message is None


class Executor:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self.http_client = http_client

    async def execute(
        self,
        *,
        method: HttpMethod,
        url: str,
        headers: dict[str, str],
        query_params: dict[str, str],
        body: str | None,
        timeout_ms: int,
        chain_context: dict[str, str],
        environment_variables: dict[str, str],
    ) -> ExecutionResult:
        try:
            resolved_url = resolve_template(url, chain_context, environment_variables)
            resolved_headers = resolve_mapping(headers, chain_context, environment_variables)
            resolved_params = resolve_mapping(query_params, chain_context, environment_variables)
            resolved_body = (
                resolve_template(body, chain_context, environment_variables) if body else None
            )
        except UndefinedVariableError as exc:
            return ExecutionResult(
                status_code=None,
                latency_ms=0,
                response_headers=None,
                response_body=None,
                error_message=str(exc),
            )

        start_time = time.perf_counter()
        try:
            response = await self.http_client.request(
                method.value,
                resolved_url,
                headers=resolved_headers,
                params=resolved_params,
                content=resolved_body,
                timeout=timeout_ms / 1000,
            )
        except httpx.TimeoutException:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ExecutionResult(
                status_code=None,
                latency_ms=latency_ms,
                response_headers=None,
                response_body=None,
                error_message=f"Request timed out after {timeout_ms}ms.",
            )
        except httpx.HTTPError as exc:
            latency_ms = int((time.perf_counter() - start_time) * 1000)
            return ExecutionResult(
                status_code=None,
                latency_ms=latency_ms,
                response_headers=None,
                response_body=None,
                error_message=f"Request failed: {exc}",
            )

        latency_ms = int((time.perf_counter() - start_time) * 1000)
        return ExecutionResult(
            status_code=response.status_code,
            latency_ms=latency_ms,
            response_headers=dict(response.headers),
            response_body=response.text,
            error_message=None,
        )