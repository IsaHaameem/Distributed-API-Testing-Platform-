"""Pydantic schemas for recurring (cron) schedules."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.validators import validate_cron_expression, validate_timezone_name


class ScheduleCreate(BaseModel):
    cron_expression: str = Field(min_length=1, max_length=120)
    timezone: str = Field(default="UTC", max_length=64)
    is_active: bool = True

    @field_validator("cron_expression")
    @classmethod
    def check_cron_expression(cls, value: str) -> str:
        return validate_cron_expression(value)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str) -> str:
        return validate_timezone_name(value)


class ScheduleUpdate(BaseModel):
    cron_expression: str | None = Field(default=None, max_length=120)
    timezone: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None

    @field_validator("cron_expression")
    @classmethod
    def check_cron_expression(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("cron_expression cannot be null; omit the field to leave it unchanged.")
        return validate_cron_expression(value)

    @field_validator("timezone")
    @classmethod
    def check_timezone(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("timezone cannot be null; omit the field to leave it unchanged.")
        return validate_timezone_name(value)

    @field_validator("is_active")
    @classmethod
    def check_is_active(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("is_active cannot be null; omit the field to leave it unchanged.")
        return value


class ScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID
    cron_expression: str
    timezone: str
    is_active: bool
    next_run_at: datetime | None
    last_run_at: datetime | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime