"""Shared Pydantic validation helpers used across multiple schema modules."""

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter

VARIABLE_NAME_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"


def validate_cron_expression(value: str) -> str:
    if not croniter.is_valid(value, strict=True):
        raise ValueError(
            "cron_expression must be a valid 5-field cron expression "
            "(minute hour day month day_of_week), e.g. '0 9 * * MON-FRI'."
        )
    return value


def validate_timezone_name(value: str) -> str:
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(
            f"'{value}' is not a recognized IANA timezone name, e.g. 'UTC' or 'America/New_York'."
        ) from exc
    return value