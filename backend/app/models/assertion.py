"""Assertion model — a check applied to every execution of an API request."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.enums import AssertionType

if TYPE_CHECKING:
    from app.models.api_request import ApiRequest


class Assertion(Base):
    __tablename__ = "assertions"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    api_request_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("api_requests.id", ondelete="CASCADE"), nullable=False
    )
    type: Mapped[AssertionType] = mapped_column(
        SAEnum(
            AssertionType,
            name="assertion_type",
            values_callable=lambda obj: [e.value for e in obj],
        ),
        nullable=False,
    )
    config: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    api_request: Mapped[ApiRequest] = relationship(back_populates="assertions")