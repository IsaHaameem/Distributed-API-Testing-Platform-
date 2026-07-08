"""Extracts variables from a completed request's response for use by later
steps in the same chain. Each rule's `save_as` value becomes available to
every subsequent request in the run via the shared chain context.
"""

import json

import jwt
from jsonpath_ng.ext import parse as parse_jsonpath

from worker.executor import ExecutionResult


class ExtractionError(Exception):
    pass


def extract_variables(
    extract_rules: list[dict], result: ExecutionResult, chain_context: dict[str, str]
) -> dict[str, str]:
    """Run every extract rule against the result, in order. Rules run in order
    because a jwt_claim rule can depend on a json_path rule earlier in the
    same list having already populated the variable it reads from."""
    parsed_body = _try_parse_json(result.response_body)
    extracted: dict[str, str] = {}
    available = {**chain_context, **extracted}

    for rule in extract_rules:
        rule_type = rule["type"]
        if rule_type == "json_path":
            value = _extract_json_path(parsed_body, rule)
        elif rule_type == "jwt_claim":
            value = _extract_jwt_claim(available, rule)
        else:
            raise ExtractionError(f"Unknown extraction rule type: {rule_type}")

        extracted[rule["save_as"]] = value
        available[rule["save_as"]] = value

    return extracted


def _try_parse_json(body: str | None):
    if not body:
        return None
    try:
        return json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None


def _extract_json_path(parsed_body, rule: dict) -> str:
    if parsed_body is None:
        raise ExtractionError(f"Cannot extract '{rule['path']}': response body is not valid JSON.")
    matches = parse_jsonpath(rule["path"]).find(parsed_body)
    if not matches:
        raise ExtractionError(f"Path '{rule['path']}' matched nothing in the response.")
    return str(matches[0].value)


def _extract_jwt_claim(available: dict[str, str], rule: dict) -> str:
    source_var = rule["source_var"]
    if source_var not in available:
        raise ExtractionError(f"jwt_claim rule references undefined variable '{source_var}'.")

    token = available[source_var]
    try:
        # Reading claims from a token issued by the target system under test,
        # purely for chaining -- not verifying our own trust of it, so no key.
        claims = jwt.decode(token, options={"verify_signature": False})
    except jwt.PyJWTError as exc:
        raise ExtractionError(f"'{source_var}' is not a decodable JWT: {exc}") from exc

    if rule["claim"] not in claims:
        raise ExtractionError(f"Claim '{rule['claim']}' not present in the JWT.")
    return str(claims[rule["claim"]])