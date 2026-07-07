"""Test task model — one queued unit of work: (test_run x api_request x optional data row)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.enums import TestTaskStatus
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.api_request import ApiRequest
    from app.models.execution_log import ExecutionLog
    from app.models.request_result import RequestResult
    from app.models.test_run import TestRun
    from app.models.worker import Worker


class TestTask(Base, TimestampMixin):
    __tablename__ = "test_tasks"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    test_run_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=False
    )
    api_request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_requests.id", ondelete="RESTRICT"), nullable=False
    )
    sequence_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    data_row_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[TestTaskStatus] = mapped_column(
        SAEnum(
            TestTaskStatus,
            name="test_task_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=TestTaskStatus.PENDING,
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    assigned_worker_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )

    test_run: Mapped[TestRun] = relationship(back_populates="test_tasks")
    api_request: Mapped[ApiRequest] = relationship(back_populates="test_tasks")
    assigned_worker: Mapped[Worker | None] = relationship(back_populates="assigned_tasks")
    request_results: Mapped[list[RequestResult]] = relationship(
        back_populates="test_task", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list[ExecutionLog]] = relationship(back_populates="test_task")