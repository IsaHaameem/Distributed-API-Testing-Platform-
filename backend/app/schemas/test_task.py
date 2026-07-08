"""Pydantic schemas for reading test tasks and their latest execution result."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import TestTaskStatus


class LatestResultRead(BaseModel):
    status_code: int | None
    latency_ms: int
    assertions_passed: bool | None
    error_message: str | None
    executed_at: datetime


class TestTaskRead(BaseModel):
    id: UUID
    test_run_id: UUID
    api_request_id: UUID
    sequence_order: int
    data_row_index: int | None
    status: TestTaskStatus
    retry_count: int
    max_retries: int
    next_retry_at: datetime | None
    latest_result: LatestResultRead | None
    created_at: datetime
    updated_at: datetime


class TestTaskListRead(BaseModel):
    tasks: list[TestTaskRead]
    total: int
    limit: int
    offset: int