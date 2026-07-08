"""Pydantic schemas for test run orchestration."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.enums import TestRunStatus, TestRunType


class TestRunCreate(BaseModel):
    data_rows: list[dict[str, str]] | None = Field(default=None)

    @field_validator("data_rows")
    @classmethod
    def validate_data_rows(cls, value: list[dict[str, str]] | None) -> list[dict[str, str]] | None:
        if value is not None and len(value) == 0:
            raise ValueError("data_rows, if provided, must contain at least one row.")
        return value


class TestRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    collection_id: UUID
    initiated_by: UUID
    status: TestRunStatus
    run_type: TestRunType
    started_at: datetime | None
    completed_at: datetime | None
    total_tasks: int
    completed_tasks: int
    failed_tasks: int
    created_at: datetime