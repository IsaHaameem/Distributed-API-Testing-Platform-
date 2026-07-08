"""Unit tests for chain-variable extraction."""

import jwt
import pytest

from worker.executor import ExecutionResult
from worker.variable_extractor import ExtractionError, extract_variables


def _result(body: str) -> ExecutionResult:
    return ExecutionResult(
        status_code=200, latency_ms=10, response_headers={}, response_body=body, error_message=None
    )


def test_extract_json_path_success() -> None:
    rules = [{"type": "json_path", "path": "$.data.token", "save_as": "authToken"}]

    extracted = extract_variables(rules, _result('{"data": {"token": "abc123"}}'), chain_context={})

    assert extracted == {"authToken": "abc123"}


def test_extract_json_path_raises_when_path_not_found() -> None:
    rules = [{"type": "json_path", "path": "$.data.missing", "save_as": "x"}]

    with pytest.raises(ExtractionError):
        extract_variables(rules, _result('{"data": {}}'), chain_context={})


def test_extract_jwt_claim_success() -> None:
    token = jwt.encode({"sub": "user-42"}, "any-secret", algorithm="HS256")
    rules = [{"type": "jwt_claim", "source_var": "authToken", "claim": "sub", "save_as": "userId"}]

    extracted = extract_variables(rules, _result("{}"), chain_context={"authToken": token})

    assert extracted == {"userId": "user-42"}


def test_extract_jwt_claim_raises_when_source_var_missing() -> None:
    rules = [{"type": "jwt_claim", "source_var": "missingToken", "claim": "sub", "save_as": "x"}]

    with pytest.raises(ExtractionError):
        extract_variables(rules, _result("{}"), chain_context={})


def test_rules_can_depend_on_earlier_rules_in_the_same_call() -> None:
    token = jwt.encode({"sub": "user-99"}, "any-secret", algorithm="HS256")
    rules = [
        {"type": "json_path", "path": "$.token", "save_as": "authToken"},
        {"type": "jwt_claim", "source_var": "authToken", "claim": "sub", "save_as": "userId"},
    ]

    extracted = extract_variables(rules, _result(f'{{"token": "{token}"}}'), chain_context={})

    assert extracted["userId"] == "user-99"


def test_raises_on_unknown_rule_type() -> None:
    rules = [{"type": "xpath", "path": "//x", "save_as": "x"}]

    with pytest.raises(ExtractionError):
        extract_variables(rules, _result("{}"), chain_context={})