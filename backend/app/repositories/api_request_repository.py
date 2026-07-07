"""API request data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.api_request import ApiRequest


class ApiRequestRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, request_id: UUID) -> ApiRequest | None:
        result = await self.session.execute(select(ApiRequest).where(ApiRequest.id == request_id))
        return result.scalar_one_or_none()

    async def list_by_collection(self, collection_id: UUID) -> list[ApiRequest]:
        result = await self.session.execute(
            select(ApiRequest)
            .where(ApiRequest.collection_id == collection_id)
            .order_by(ApiRequest.order_index, ApiRequest.created_at)
        )
        return list(result.scalars().all())

    async def create(self, *, collection_id: UUID, **fields) -> ApiRequest:
        request = ApiRequest(collection_id=collection_id, **fields)
        self.session.add(request)
        await self.session.flush()
        await self.session.refresh(request)
        return request

    async def update(self, request: ApiRequest, **fields) -> ApiRequest:
        for key, value in fields.items():
            setattr(request, key, value)
        await self.session.flush()
        await self.session.refresh(request)
        return request

    async def delete(self, request: ApiRequest) -> None:
        await self.session.delete(request)
        await self.session.flush()