"""Execution log model — structured log lines for a test run / task."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.enums import LogLevel

if TYPE_CHECKING:
    from app.models.test_run import TestRun
    from app.models.test_task import TestTask


class ExecutionLog(Base):
    __tablename__ = "execution_logs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    test_run_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_runs.id", ondelete="CASCADE"), nullable=True
    )
    test_task_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("test_tasks.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[LogLevel] = mapped_column(
        SAEnum(LogLevel, name="log_level", values_callable=lambda obj: [e.value for e in obj]),
        nullable=False,
        default=LogLevel.INFO,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    log_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    test_run: Mapped[TestRun | None] = relationship(back_populates="execution_logs")
    test_task: Mapped[TestTask | None] = relationship(back_populates="execution_logs")