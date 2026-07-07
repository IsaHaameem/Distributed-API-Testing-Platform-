"""Organization business logic: CRUD plus membership and role authorization."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    AlreadyMemberError,
    CannotRemoveLastOwnerError,
    InsufficientPermissionsError,
    MembershipNotFoundError,
    OrganizationNotFoundError,
    SlugAlreadyTakenError,
    UserNotFoundError,
)
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.services.authorization import ADMIN_ROLES, require_membership


class OrganizationService:
    def __init__(
        self,
        organization_repository: OrganizationRepository,
        member_repository: OrganizationMemberRepository,
        user_repository: UserRepository,
    ) -> None:
        self.organization_repository = organization_repository
        self.member_repository = member_repository
        self.user_repository = user_repository

    async def create_organization(
        self, *, current_user: User, name: str, slug: str
    ) -> tuple[Organization, OrganizationRole]:
        try:
            organization = await self.organization_repository.create(name=name, slug=slug)
            await self.member_repository.add_member(
                organization_id=organization.id,
                user_id=current_user.id,
                role=OrganizationRole.OWNER,
            )
        except IntegrityError as exc:
            raise SlugAlreadyTakenError() from exc

        return organization, OrganizationRole.OWNER

    async def list_my_organizations(
        self, *, current_user: User
    ) -> list[tuple[Organization, OrganizationRole]]:
        return await self.member_repository.list_organizations_for_user(current_user.id)

    async def get_organization(
        self, *, current_user: User, organization_id: UUID
    ) -> tuple[Organization, OrganizationRole]:
        membership = await require_membership(self.member_repository, organization_id, current_user.id)
        organization = await self.organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError()
        return organization, membership.role

    async def update_organization(
        self,
        *,
        current_user: User,
        organization_id: UUID,
        name: str | None,
        slug: str | None,
    ) -> tuple[Organization, OrganizationRole]:
        membership = await require_membership(
            self.member_repository, organization_id, current_user.id, ADMIN_ROLES
        )
        organization = await self.organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError()

        try:
            organization = await self.organization_repository.update(
                organization, name=name, slug=slug
            )
        except IntegrityError as exc:
            raise SlugAlreadyTakenError() from exc

        return organization, membership.role

    async def delete_organization(self, *, current_user: User, organization_id: UUID) -> None:
        await require_membership(
            self.member_repository, organization_id, current_user.id, {OrganizationRole.OWNER}
        )
        organization = await self.organization_repository.get_by_id(organization_id)
        if organization is None:
            raise OrganizationNotFoundError()
        await self.organization_repository.delete(organization)

    async def list_members(
        self, *, current_user: User, organization_id: UUID
    ) -> list[OrganizationMember]:
        await require_membership(self.member_repository, organization_id, current_user.id)
        return await self.member_repository.list_members(organization_id)

    async def add_member(
        self,
        *,
        current_user: User,
        organization_id: UUID,
        email: str,
        role: OrganizationRole,
    ) -> OrganizationMember:
        current_membership = await require_membership(
            self.member_repository, organization_id, current_user.id, ADMIN_ROLES
        )

        if role in ADMIN_ROLES and current_membership.role != OrganizationRole.OWNER:
            raise InsufficientPermissionsError()

        target_user = await self.user_repository.get_by_email(email.strip().lower())
        if target_user is None:
            raise UserNotFoundError()

        existing = await self.member_repository.get_membership(organization_id, target_user.id)
        if existing is not None:
            raise AlreadyMemberError()

        try:
            return await self.member_repository.add_member(
                organization_id=organization_id, user_id=target_user.id, role=role
            )
        except IntegrityError as exc:
            raise AlreadyMemberError() from exc

    async def update_member_role(
        self,
        *,
        current_user: User,
        organization_id: UUID,
        target_user_id: UUID,
        role: OrganizationRole,
    ) -> OrganizationMember:
        await require_membership(
            self.member_repository, organization_id, current_user.id, {OrganizationRole.OWNER}
        )

        membership = await self.member_repository.get_membership(organization_id, target_user_id)
        if membership is None:
            raise MembershipNotFoundError()

        if membership.role == OrganizationRole.OWNER and role != OrganizationRole.OWNER:
            owner_count = await self.member_repository.count_owners(organization_id)
            if owner_count <= 1:
                raise CannotRemoveLastOwnerError()

        return await self.member_repository.update_role(membership, role)

    async def remove_member(
        self, *, current_user: User, organization_id: UUID, target_user_id: UUID
    ) -> None:
        is_self_removal = current_user.id == target_user_id

        if is_self_removal:
            membership = await require_membership(self.member_repository, organization_id, current_user.id)
        else:
            await require_membership(
                self.member_repository, organization_id, current_user.id, {OrganizationRole.OWNER}
            )
            membership = await self.member_repository.get_membership(organization_id, target_user_id)
            if membership is None:
                raise MembershipNotFoundError()

        if membership.role == OrganizationRole.OWNER:
            owner_count = await self.member_repository.count_owners(organization_id)
            if owner_count <= 1:
                raise CannotRemoveLastOwnerError()

        await self.member_repository.remove_member(membership)