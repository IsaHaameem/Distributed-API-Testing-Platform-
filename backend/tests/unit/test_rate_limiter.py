"""Unit tests for RateLimiter.host_for_url -- pure URL parsing, no Redis
needed. The actual token-bucket algorithm lives entirely inside a Lua
script that runs server-side in Redis; there's no separate Python-side
bucket math to unit-test in isolation, so that behavior is covered by the
integration tests instead (tests/integration/test_rate_limiter.py)."""

from app.queue.rate_limiter import RateLimiter


def test_host_for_url_extracts_hostname() -> None:
    assert RateLimiter.host_for_url("https://api.example.com/v1/users") == "api.example.com"


def test_host_for_url_is_case_insensitive() -> None:
    assert RateLimiter.host_for_url("https://API.Example.COM/path") == "api.example.com"


def test_host_for_url_ignores_port() -> None:
    assert RateLimiter.host_for_url("https://api.example.com:8443/path") == "api.example.com"


def test_host_for_url_ignores_path_and_query() -> None:
    assert (
        RateLimiter.host_for_url("https://api.example.com/a/b/c?x=1&y=2") == "api.example.com"
    )


def test_host_for_url_returns_none_for_unparseable_host() -> None:
    assert RateLimiter.host_for_url("not-a-url-at-all") is None


def test_host_for_url_returns_none_for_empty_string() -> None:
    assert RateLimiter.host_for_url("") is None
