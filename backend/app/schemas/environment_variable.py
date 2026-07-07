"""Pydantic schemas for project-scoped environment variables."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.validators import VARIABLE_NAME_PATTERN

_MASK = "********"


class EnvironmentVariableCreate(BaseModel):
    key: str = Field(min_length=1, max_length=255, pattern=VARIABLE_NAME_PATTERN)
    value: str = Field(max_length=8192)
    is_secret: bool = False


class EnvironmentVariableUpdate(BaseModel):
    key: str | None = Field(default=None, max_length=255, pattern=VARIABLE_NAME_PATTERN)
    value: str | None = Field(default=None, max_length=8192)
    is_secret: bool | None = None

    @field_validator("key")
    @classmethod
    def validate_key(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("key cannot be null; omit the field to leave it unchanged.")
        return value

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("value cannot be null; omit the field to leave it unchanged.")
        return value

    @field_validator("is_secret")
    @classmethod
    def validate_is_secret(cls, value: bool | None) -> bool:
        if value is None:
            raise ValueError("is_secret cannot be null; omit the field to leave it unchanged.")
        return value


class EnvironmentVariableRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    key: str
    value: str
    is_secret: bool
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def mask_secret_value(self) -> "EnvironmentVariableRead":
        if self.is_secret:
            self.value = _MASK
        return self