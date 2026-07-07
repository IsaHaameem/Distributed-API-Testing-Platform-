"""Organization membership data-access layer."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember


class OrganizationMemberRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_membership(
        self, organization_id: UUID, user_id: UUID
    ) -> OrganizationMember | None:
        result = await self.session.execute(
            select(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.user_id == user_id,
            )
            .options(selectinload(OrganizationMember.user))
        )
        return result.scalar_one_or_none()

    async def list_members(self, organization_id: UUID) -> list[OrganizationMember]:
        result = await self.session.execute(
            select(OrganizationMember)
            .where(OrganizationMember.organization_id == organization_id)
            .options(selectinload(OrganizationMember.user))
            .order_by(OrganizationMember.created_at)
        )
        return list(result.scalars().all())

    async def list_organizations_for_user(
        self, user_id: UUID
    ) -> list[tuple[Organization, OrganizationRole]]:
        result = await self.session.execute(
            select(Organization, OrganizationMember.role)
            .join(OrganizationMember, OrganizationMember.organization_id == Organization.id)
            .where(OrganizationMember.user_id == user_id)
            .order_by(Organization.created_at)
        )
        return [(row[0], row[1]) for row in result.all()]

    async def add_member(
        self, *, organization_id: UUID, user_id: UUID, role: OrganizationRole
    ) -> OrganizationMember:
        membership = OrganizationMember(organization_id=organization_id, user_id=user_id, role=role)
        self.session.add(membership)
        await self.session.flush()

        refreshed = await self.get_membership(organization_id, user_id)
        assert refreshed is not None  # just inserted in this same transaction
        return refreshed

    async def update_role(
        self, membership: OrganizationMember, role: OrganizationRole
    ) -> OrganizationMember:
        membership.role = role
        await self.session.flush()
        return membership

    async def remove_member(self, membership: OrganizationMember) -> None:
        await self.session.delete(membership)
        await self.session.flush()

    async def count_owners(self, organization_id: UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(OrganizationMember)
            .where(
                OrganizationMember.organization_id == organization_id,
                OrganizationMember.role == OrganizationRole.OWNER,
            )
        )
        return result.scalar_one()