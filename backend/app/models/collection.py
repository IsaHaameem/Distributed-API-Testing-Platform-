"""Collection model — a named group of API requests."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.api_request import ApiRequest
    from app.models.project import Project
    from app.models.schedule import Schedule
    from app.models.test_run import TestRun


class Collection(Base, TimestampMixin):
    __tablename__ = "collections"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    project_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    project: Mapped[Project] = relationship(back_populates="collections")
    api_requests: Mapped[list[ApiRequest]] = relationship(
        back_populates="collection",
        cascade="all, delete-orphan",
        order_by="ApiRequest.order_index",
    )
    test_runs: Mapped[list[TestRun]] = relationship(back_populates="collection")
    schedules: Mapped[list[Schedule]] = relationship(
        back_populates="collection", cascade="all, delete-orphan"
    )