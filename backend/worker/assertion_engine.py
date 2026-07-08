"""Evaluates assertions against an execution result. Each assertion type
maps to exactly one check; a task's assertions all need to pass for the
task to be considered successful."""

import json
from dataclasses import dataclass

from jsonpath_ng.ext import parse as parse_jsonpath

from worker.executor import ExecutionResult


@dataclass
class AssertionOutcome:
    assertion_id: str
    assertion_type: str
    passed: bool
    detail: str


def evaluate_assertions(assertions: list, result: ExecutionResult) -> list[AssertionOutcome]:
    """Run every assertion against the result. Returns one outcome per assertion;
    callers decide pass/fail for the whole task from `all(o.passed for o in outcomes)`.
    """
    parsed_body = _try_parse_json(result.response_body)
    return [_evaluate_one(assertion, result, parsed_body) for assertion in assertions]


def _evaluate_one(assertion, result: ExecutionResult, parsed_body) -> AssertionOutcome:
    assertion_type = assertion.type.value
    config = assertion.config

    try:
        if assertion_type == "status_code_equals":
            passed, detail = _check_status_code_equals(result, config)
        elif assertion_type == "json_path_equals":
            passed, detail = _check_json_path_equals(parsed_body, config)
        elif assertion_type == "json_path_exists":
            passed, detail = _check_json_path_exists(parsed_body, config)
        elif assertion_type == "response_time_below":
            passed, detail = _check_response_time_below(result, config)
        elif assertion_type == "header_equals":
            passed, detail = _check_header_equals(result, config)
        else:
            passed, detail = False, f"Unknown assertion type: {assertion_type}"
    except Exception as exc:
        passed, detail = False, f"Assertion raised an error: {exc}"

    return AssertionOutcome(
        assertion_id=str(assertion.id), assertion_type=assertion_type, passed=passed, detail=detail
    )


def _try_parse_json(body: str | None):
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


def _check_status_code_equals(result: ExecutionResult, config: dict) -> tuple[bool, str]:
    expected = config["expected"]
    actual = result.status_code
    return actual == expected, f"expected status {expected}, got {actual}"


def _check_json_path_equals(parsed_body, config: dict) -> tuple[bool, str]:
    if parsed_body is None:
        return False, "response body is not valid JSON"
    path, expected = config["path"], config["expected"]
    matches = parse_jsonpath(path).find(parsed_body)
    if not matches:
        return False, f"path '{path}' matched nothing"
    actual = matches[0].value
    return actual == expected, f"path '{path}': expected {expected!r}, got {actual!r}"


def _check_json_path_exists(parsed_body, config: dict) -> tuple[bool, str]:
    if parsed_body is None:
        return False, "response body is not valid JSON"
    path = config["path"]
    matches = parse_jsonpath(path).find(parsed_body)
    return len(matches) > 0, f"path '{path}' {'matched' if matches else 'did not match'}"


def _check_response_time_below(result: ExecutionResult, config: dict) -> tuple[bool, str]:
    max_ms = config["max_ms"]
    return result.latency_ms < max_ms, f"expected under {max_ms}ms, took {result.latency_ms}ms"


def _check_header_equals(result: ExecutionResult, config: dict) -> tuple[bool, str]:
    header, expected = config["header"], config["expected"]
    headers = result.response_headers or {}
    # HTTP headers are case-insensitive; keys in response_headers may not
    # match the case the assertion was configured with.
    actual = next((v for k, v in headers.items() if k.lower() == header.lower()), None)
    return actual == expected, f"header '{header}': expected {expected!r}, got {actual!r}"