"""Worker model — the durable registry record for a worker process."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.enums import WorkerStatus

if TYPE_CHECKING:
    from app.models.request_result import RequestResult
    from app.models.test_task import TestTask
    from app.models.worker_heartbeat import WorkerHeartbeat


class Worker(Base):
    __tablename__ = "workers"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    hostname: Mapped[str] = mapped_column(String(255), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[WorkerStatus] = mapped_column(
        SAEnum(
            WorkerStatus, name="worker_status", values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False,
        default=WorkerStatus.ONLINE,
    )
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    heartbeats: Mapped[list[WorkerHeartbeat]] = relationship(
        back_populates="worker", cascade="all, delete-orphan"
    )
    assigned_tasks: Mapped[list[TestTask]] = relationship(back_populates="assigned_worker")
    executed_results: Mapped[list[RequestResult]] = relationship(
        back_populates="executed_by_worker"
    )