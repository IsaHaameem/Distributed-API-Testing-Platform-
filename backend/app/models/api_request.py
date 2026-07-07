"""API request model — a saved, templated request definition (the 'Request Template' feature)."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.identifiers import generate_uuid7
from app.database import Base
from app.models.enums import HttpMethod
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.assertion import Assertion
    from app.models.collection import Collection
    from app.models.test_task import TestTask


class ApiRequest(Base, TimestampMixin):
    __tablename__ = "api_requests"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=generate_uuid7
    )
    collection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("collections.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    method: Mapped[HttpMethod] = mapped_column(
        SAEnum(
            HttpMethod, name="http_method", values_callable=lambda obj: [e.value for e in obj]
        ),
        nullable=False,
    )
    url: Mapped[str] = mapped_column(Text, nullable=False)
    headers: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    query_params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timeout_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=30000)
    extract_rules: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    collection: Mapped[Collection] = relationship(back_populates="api_requests")
    assertions: Mapped[list[Assertion]] = relationship(
        back_populates="api_request", cascade="all, delete-orphan"
    )
    test_tasks: Mapped[list[TestTask]] = relationship(back_populates="api_request")