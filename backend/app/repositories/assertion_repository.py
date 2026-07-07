"""Assertion data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assertion import Assertion
from app.models.enums import AssertionType


class AssertionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, assertion_id: UUID) -> Assertion | None:
        result = await self.session.execute(select(Assertion).where(Assertion.id == assertion_id))
        return result.scalar_one_or_none()

    async def list_by_request(self, api_request_id: UUID) -> list[Assertion]:
        result = await self.session.execute(
            select(Assertion)
            .where(Assertion.api_request_id == api_request_id)
            .order_by(Assertion.created_at)
        )
        return list(result.scalars().all())

    async def create(self, *, api_request_id: UUID, type_: str, config: dict) -> Assertion:
        assertion = Assertion(api_request_id=api_request_id, type=AssertionType(type_), config=config)
        self.session.add(assertion)
        await self.session.flush()
        await self.session.refresh(assertion)
        return assertion

    async def delete(self, assertion: Assertion) -> None:
        await self.session.delete(assertion)
        await self.session.flush()