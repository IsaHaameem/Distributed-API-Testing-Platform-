"""Project model."""

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
    from app.models.collection import Collection
    from app.models.environment_variable import EnvironmentVariable
    from app.models.organization import Organization
    from app.models.user import User


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    organization_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    organization: Mapped[Organization] = relationship(back_populates="projects")
    created_by_user: Mapped[User] = relationship(back_populates="created_projects")
    collections: Mapped[list[Collection]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    environment_variables: Mapped[list[EnvironmentVariable]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )