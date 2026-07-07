"""Pydantic schemas for API requests and their variable-extraction rules."""

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import HttpMethod
from app.schemas.validators import VARIABLE_NAME_PATTERN


class JsonPathExtractRule(BaseModel):
    type: Literal["json_path"]
    path: str = Field(min_length=1, max_length=500)
    save_as: str = Field(min_length=1, max_length=100, pattern=VARIABLE_NAME_PATTERN)

    @field_validator("path")
    @classmethod
    def path_looks_like_jsonpath(cls, value: str) -> str:
        if not value.startswith("$"):
            raise ValueError("path must be a JSONPath expression starting with '$'.")
        return value


class JwtClaimExtractRule(BaseModel):
    type: Literal["jwt_claim"]
    source_var: str = Field(min_length=1, max_length=100, pattern=VARIABLE_NAME_PATTERN)
    claim: str = Field(min_length=1, max_length=100)
    save_as: str = Field(min_length=1, max_length=100, pattern=VARIABLE_NAME_PATTERN)


ExtractRule = Annotated[
    Union[JsonPathExtractRule, JwtClaimExtractRule],
    Field(discriminator="type"),
]


class ApiRequestCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    method: HttpMethod
    url: str = Field(min_length=1, max_length=2000)
    headers: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, str] = Field(default_factory=dict)
    body: str | None = Field(default=None, max_length=65536)
    order_index: int | None = Field(default=None, ge=0)
    timeout_ms: int = Field(default=30000, ge=100, le=300000)
    extract_rules: list[ExtractRule] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank.")
        return stripped

    @field_validator("url")
    @classmethod
    def strip_url(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("url cannot be blank.")
        return stripped


class ApiRequestUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=255)
    method: HttpMethod | None = None
    url: str | None = Field(default=None, max_length=2000)
    headers: dict[str, str] | None = None
    query_params: dict[str, str] | None = None
    body: str | None = Field(default=None, max_length=65536)
    order_index: int | None = Field(default=None, ge=0)
    timeout_ms: int | None = Field(default=None, ge=100, le=300000)
    extract_rules: list[ExtractRule] | None = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("name cannot be null; omit the field to leave it unchanged.")
        stripped = value.strip()
        if not stripped:
            raise ValueError("name cannot be blank.")
        return stripped

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: HttpMethod | None) -> HttpMethod:
        if value is None:
            raise ValueError("method cannot be null; omit the field to leave it unchanged.")
        return value

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str | None) -> str:
        if value is None:
            raise ValueError("url cannot be null; omit the field to leave it unchanged.")
        stripped = value.strip()
        if not stripped:
            raise ValueError("url cannot be blank.")
        return stripped

    @field_validator("headers")
    @classmethod
    def validate_headers(cls, value: dict[str, str] | None) -> dict[str, str]:
        if value is None:
            raise ValueError("headers cannot be null; send {} to clear it, or omit the field.")
        return value

    @field_validator("query_params")
    @classmethod
    def validate_query_params(cls, value: dict[str, str] | None) -> dict[str, str]:
        if value is None:
            raise ValueError("query_params cannot be null; send {} to clear it, or omit the field.")
        return value

    @field_validator("order_index")
    @classmethod
    def validate_order_index(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("order_index cannot be null; omit the field to leave it unchanged.")
        return value

    @field_validator("timeout_ms")
    @classmethod
    def validate_timeout(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("timeout_ms cannot be null; omit the field to leave it unchanged.")
        return value

    @field_validator("extract_rules")
    @classmethod
    def validate_extract_rules(cls, value: list | None) -> list:
        if value is None:
            raise ValueError("extract_rules cannot be null; send [] to clear it, or omit the field.")
        return value


class ApiRequestRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID
    name: str
    method: HttpMethod
    url: str
    headers: dict[str, str]
    query_params: dict[str, str]
    body: str | None
    order_index: int
    timeout_ms: int
    extract_rules: list[dict]
    created_at: datetime
    updated_at: datetime