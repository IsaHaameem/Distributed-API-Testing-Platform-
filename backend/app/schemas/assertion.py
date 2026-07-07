"""Pydantic schemas for assertions -- checks run against every execution of an API request."""

from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import AssertionType


class StatusCodeEqualsConfig(BaseModel):
    expected: int = Field(ge=100, le=599)


class JsonPathEqualsConfig(BaseModel):
    path: str = Field(min_length=1, max_length=500)
    expected: str | int | float | bool


class JsonPathExistsConfig(BaseModel):
    path: str = Field(min_length=1, max_length=500)


class ResponseTimeBelowConfig(BaseModel):
    max_ms: int = Field(gt=0, le=300000)


class HeaderEqualsConfig(BaseModel):
    header: str = Field(min_length=1, max_length=255)
    expected: str = Field(max_length=2000)


class StatusCodeEqualsAssertion(BaseModel):
    type: Literal["status_code_equals"]
    config: StatusCodeEqualsConfig


class JsonPathEqualsAssertion(BaseModel):
    type: Literal["json_path_equals"]
    config: JsonPathEqualsConfig


class JsonPathExistsAssertion(BaseModel):
    type: Literal["json_path_exists"]
    config: JsonPathExistsConfig


class ResponseTimeBelowAssertion(BaseModel):
    type: Literal["response_time_below"]
    config: ResponseTimeBelowConfig


class HeaderEqualsAssertion(BaseModel):
    type: Literal["header_equals"]
    config: HeaderEqualsConfig


AssertionCreate = Annotated[
    Union[
        StatusCodeEqualsAssertion,
        JsonPathEqualsAssertion,
        JsonPathExistsAssertion,
        ResponseTimeBelowAssertion,
        HeaderEqualsAssertion,
    ],
    Field(discriminator="type"),
]


class AssertionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    api_request_id: UUID
    type: AssertionType
    config: dict
    created_at: datetime