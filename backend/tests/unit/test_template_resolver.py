"""Unit tests for template variable resolution."""

import pytest

from worker.template_resolver import UndefinedVariableError, resolve_mapping, resolve_template


def test_resolves_from_chain_context() -> None:
    result = resolve_template("{{token}}", chain_context={"token": "abc123"}, environment_variables={})
    assert result == "abc123"


def test_resolves_from_environment_variables() -> None:
    result = resolve_template(
        "{{baseUrl}}/users",
        chain_context={},
        environment_variables={"baseUrl": "https://api.example.com"},
    )
    assert result == "https://api.example.com/users"


def test_chain_context_takes_precedence_over_environment_variables() -> None:
    result = resolve_template(
        "{{env}}", chain_context={"env": "from-chain"}, environment_variables={"env": "from-project"}
    )
    assert result == "from-chain"


def test_raises_on_undefined_variable() -> None:
    with pytest.raises(UndefinedVariableError) as exc_info:
        resolve_template("{{missing}}", chain_context={}, environment_variables={})
    assert exc_info.value.variable_name == "missing"


def test_handles_multiple_placeholders_in_one_string() -> None:
    result = resolve_template(
        "{{baseUrl}}/users/{{userId}}",
        chain_context={"userId": "42"},
        environment_variables={"baseUrl": "https://api.example.com"},
    )
    assert result == "https://api.example.com/users/42"


def test_handles_string_with_no_placeholders() -> None:
    result = resolve_template("no variables here", chain_context={}, environment_variables={})
    assert result == "no variables here"


def test_resolve_mapping_resolves_every_value() -> None:
    result = resolve_mapping(
        {"Authorization": "Bearer {{token}}", "Content-Type": "application/json"},
        chain_context={"token": "abc123"},
        environment_variables={},
    )
    assert result == {"Authorization": "Bearer abc123", "Content-Type": "application/json"}