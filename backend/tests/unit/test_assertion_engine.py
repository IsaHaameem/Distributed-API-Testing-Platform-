"""Unit tests for assertion evaluation."""

from types import SimpleNamespace
from uuid import uuid4

from worker.assertion_engine import evaluate_assertions
from worker.executor import ExecutionResult


def _assertion(assertion_type: str, config: dict):
    """A lightweight double matching the shape evaluate_assertions actually
    reads (id, type.value, config) -- no need for a real ORM object or a
    database for what is fundamentally pure logic."""
    return SimpleNamespace(id=uuid4(), type=SimpleNamespace(value=assertion_type), config=config)


def _result(**overrides) -> ExecutionResult:
    defaults = dict(
        status_code=200, latency_ms=50, response_headers={}, response_body="{}", error_message=None
    )
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def test_status_code_equals_pass_and_fail() -> None:
    assertions = [_assertion("status_code_equals", {"expected": 200})]

    passing = evaluate_assertions(assertions, _result(status_code=200))
    failing = evaluate_assertions(assertions, _result(status_code=404))

    assert passing[0].passed is True
    assert failing[0].passed is False


def test_json_path_equals_pass_and_fail() -> None:
    assertions = [_assertion("json_path_equals", {"path": "$.status", "expected": "ok"})]

    passing = evaluate_assertions(assertions, _result(response_body='{"status": "ok"}'))
    failing = evaluate_assertions(assertions, _result(response_body='{"status": "error"}'))

    assert passing[0].passed is True
    assert failing[0].passed is False


def test_json_path_exists_pass_and_fail() -> None:
    assertions = [_assertion("json_path_exists", {"path": "$.data.token"})]

    passing = evaluate_assertions(assertions, _result(response_body='{"data": {"token": "x"}}'))
    failing = evaluate_assertions(assertions, _result(response_body='{"data": {}}'))

    assert passing[0].passed is True
    assert failing[0].passed is False


def test_response_time_below_pass_and_fail() -> None:
    assertions = [_assertion("response_time_below", {"max_ms": 100})]

    passing = evaluate_assertions(assertions, _result(latency_ms=50))
    failing = evaluate_assertions(assertions, _result(latency_ms=150))

    assert passing[0].passed is True
    assert failing[0].passed is False


def test_header_equals_is_case_insensitive() -> None:
    assertions = [
        _assertion("header_equals", {"header": "Content-Type", "expected": "application/json"})
    ]

    outcome = evaluate_assertions(
        assertions, _result(response_headers={"content-type": "application/json"})
    )

    assert outcome[0].passed is True


def test_json_path_assertion_fails_gracefully_on_non_json_body() -> None:
    assertions = [_assertion("json_path_exists", {"path": "$.data"})]

    outcome = evaluate_assertions(assertions, _result(response_body="not json at all"))

    assert outcome[0].passed is False


def test_evaluate_assertions_returns_one_outcome_per_assertion() -> None:
    assertions = [
        _assertion("status_code_equals", {"expected": 200}),
        _assertion("response_time_below", {"max_ms": 1000}),
    ]

    outcomes = evaluate_assertions(assertions, _result())

    assert len(outcomes) == 2