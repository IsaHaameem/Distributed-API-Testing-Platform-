"""Resolves {{variable}} placeholders in request templates against chain
context (values extracted from earlier steps in the same run) and project
environment variables. Chain context takes precedence -- it's more specific
and more recently established than a project-wide default.
"""

import re

_PLACEHOLDER_PATTERN = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}")


class UndefinedVariableError(Exception):
    """Raised when a template references a variable that isn't defined
    anywhere -- deliberately a hard failure rather than leaving the
    placeholder in place, since a URL or header with a literal "{{foo}}"
    still in it produces a confusing downstream failure instead of a clear
    one right here."""

    def __init__(self, variable_name: str) -> None:
        self.variable_name = variable_name
        super().__init__(f"Undefined variable: {variable_name}")


def resolve_template(
    template: str, chain_context: dict[str, str], environment_variables: dict[str, str]
) -> str:
    """Replace every {{name}} in `template` with its resolved value."""

    def _replace(match: re.Match) -> str:
        name = match.group(1)
        if name in chain_context:
            return str(chain_context[name])
        if name in environment_variables:
            return str(environment_variables[name])
        raise UndefinedVariableError(name)

    return _PLACEHOLDER_PATTERN.sub(_replace, template)


def resolve_mapping(
    mapping: dict[str, str], chain_context: dict[str, str], environment_variables: dict[str, str]
) -> dict[str, str]:
    """Resolve templates in every value of a dict (used for headers and query_params)."""
    return {
        key: resolve_template(value, chain_context, environment_variables)
        for key, value in mapping.items()
    }