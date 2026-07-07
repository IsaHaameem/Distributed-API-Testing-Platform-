"""Collection data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.collection import Collection


class CollectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, collection_id: UUID) -> Collection | None:
        result = await self.session.execute(
            select(Collection).where(Collection.id == collection_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(self, project_id: UUID) -> list[Collection]:
        result = await self.session.execute(
            select(Collection).where(Collection.project_id == project_id).order_by(Collection.created_at)
        )
        return list(result.scalars().all())

    async def create(self, *, project_id: UUID, name: str, description: str | None) -> Collection:
        collection = Collection(project_id=project_id, name=name, description=description)
        self.session.add(collection)
        await self.session.flush()
        await self.session.refresh(collection)
        return collection

    async def update(self, collection: Collection, **fields) -> Collection:
        for key, value in fields.items():
            setattr(collection, key, value)
        await self.session.flush()
        await self.session.refresh(collection)
        return collection

    async def delete(self, collection: Collection) -> None:
        await self.session.delete(collection)
        await self.session.flush()