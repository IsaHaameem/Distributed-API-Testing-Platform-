"""User model."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.organization_member import OrganizationMember
    from app.models.project import Project
    from app.models.schedule import Schedule
    from app.models.test_run import TestRun


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    memberships: Mapped[list[OrganizationMember]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    created_projects: Mapped[list[Project]] = relationship(back_populates="created_by_user")
    initiated_test_runs: Mapped[list[TestRun]] = relationship(back_populates="initiated_by_user")
    created_schedules: Mapped[list[Schedule]] = relationship(back_populates="created_by_user")