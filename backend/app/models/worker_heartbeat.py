"""Worker heartbeat model — periodic liveness pings; Redis is the real-time source of truth, this is the historical record."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base

if TYPE_CHECKING:
    from app.models.worker import Worker


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    worker_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    heartbeat_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    active_tasks_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cpu_usage: Mapped[float | None] = mapped_column(Float, nullable=True)
    memory_usage: Mapped[float | None] = mapped_column(Float, nullable=True)

    worker: Mapped[Worker] = relationship(back_populates="heartbeats")