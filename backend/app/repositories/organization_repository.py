"""Organization data-access layer."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organization import Organization


class OrganizationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, organization_id: UUID) -> Organization | None:
        result = await self.session.execute(
            select(Organization).where(Organization.id == organization_id)
        )
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organization | None:
        result = await self.session.execute(select(Organization).where(Organization.slug == slug))
        return result.scalar_one_or_none()

    async def create(self, *, name: str, slug: str) -> Organization:
        organization = Organization(name=name, slug=slug)
        self.session.add(organization)
        await self.session.flush()
        await self.session.refresh(organization)
        return organization

    async def update(
        self, organization: Organization, *, name: str | None = None, slug: str | None = None
    ) -> Organization:
        if name is not None:
            organization.name = name
        if slug is not None:
            organization.slug = slug
        await self.session.flush()
        await self.session.refresh(organization)
        return organization

    async def delete(self, organization: Organization) -> None:
        await self.session.delete(organization)
        await self.session.flush()