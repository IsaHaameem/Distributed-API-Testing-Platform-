"""Test run model — one execution of a collection."""

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
from app.models.enums import TestRunStatus, TestRunType
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.execution_log import ExecutionLog
    from app.models.test_task import TestTask
    from app.models.user import User


class TestRun(Base, TimestampMixin):
    __tablename__ = "test_runs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    initiated_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[TestRunStatus] = mapped_column(
        SAEnum(
            TestRunStatus,
            name="test_run_status",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
        default=TestRunStatus.PENDING,
    )
    run_type: Mapped[TestRunType] = mapped_column(
        SAEnum(
            TestRunType, name="test_run_type", values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False,
        default=TestRunType.MANUAL,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    total_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_tasks: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    collection: Mapped[Collection] = relationship(back_populates="test_runs")
    initiated_by_user: Mapped[User] = relationship(back_populates="initiated_test_runs")
    test_tasks: Mapped[list[TestTask]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )
    execution_logs: Mapped[list[ExecutionLog]] = relationship(
        back_populates="test_run", cascade="all, delete-orphan"
    )