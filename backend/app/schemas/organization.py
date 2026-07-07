"""Pydantic schemas for organizations and organization membership."""

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.enums import OrganizationRole

_SLUG_PATTERN = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_SLUG_HELP = (
    "slug must be lowercase letters, numbers, and single hyphens only "
    "(e.g. 'my-team'), with no leading, trailing, or repeated hyphens."
)


class OrganizationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=255)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank.")
        return stripped

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        if not _SLUG_PATTERN.match(value):
            raise ValueError(_SLUG_HELP)
        return value


class OrganizationUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    slug: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null; omit the field to leave it unchanged.")
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank.")
        return stripped

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("slug cannot be null; omit the field to leave it unchanged.")
        if not _SLUG_PATTERN.match(value):
            raise ValueError(_SLUG_HELP)
        return value


class OrganizationRead(BaseModel):
    id: UUID
    name: str
    slug: str
    my_role: OrganizationRole
    created_at: datetime
    updated_at: datetime


class MemberAdd(BaseModel):
    email: EmailStr
    role: OrganizationRole = OrganizationRole.MEMBER


class MemberRoleUpdate(BaseModel):
    role: OrganizationRole


class MemberRead(BaseModel):
    user_id: UUID
    email: EmailStr
    full_name: str
    role: OrganizationRole
    joined_at: datetime