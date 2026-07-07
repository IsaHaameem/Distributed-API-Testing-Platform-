"""Organization and membership endpoints."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.enums import OrganizationRole
from app.models.organization import Organization
from app.models.organization_member import OrganizationMember
from app.models.user import User
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.organization_repository import OrganizationRepository
from app.repositories.user_repository import UserRepository
from app.schemas.organization import (
    MemberAdd,
    MemberRead,
    MemberRoleUpdate,
    OrganizationCreate,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services.organization_service import OrganizationService

router = APIRouter(prefix="/organizations", tags=["organizations"])


def get_organization_service(db: AsyncSession = Depends(get_db)) -> OrganizationService:
    return OrganizationService(
        OrganizationRepository(db),
        OrganizationMemberRepository(db),
        UserRepository(db),
    )


def _to_read(organization: Organization, role: OrganizationRole) -> OrganizationRead:
    return OrganizationRead(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        my_role=role,
        created_at=organization.created_at,
        updated_at=organization.updated_at,
    )


def _member_to_read(membership: OrganizationMember) -> MemberRead:
    return MemberRead(
        user_id=membership.user.id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        role=membership.role,
        joined_at=membership.created_at,
    )


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
async def create_organization(
    payload: OrganizationCreate,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationRead:
    organization, role = await service.create_organization(
        current_user=current_user, name=payload.name, slug=payload.slug
    )
    return _to_read(organization, role)


@router.get("", response_model=list[OrganizationRead])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> list[OrganizationRead]:
    organizations = await service.list_my_organizations(current_user=current_user)
    return [_to_read(org, role) for org, role in organizations]


@router.get("/{organization_id}", response_model=OrganizationRead)
async def get_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationRead:
    organization, role = await service.get_organization(
        current_user=current_user, organization_id=organization_id
    )
    return _to_read(organization, role)


@router.patch("/{organization_id}", response_model=OrganizationRead)
async def update_organization(
    organization_id: UUID,
    payload: OrganizationUpdate,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> OrganizationRead:
    organization, role = await service.update_organization(
        current_user=current_user,
        organization_id=organization_id,
        name=payload.name,
        slug=payload.slug,
    )
    return _to_read(organization, role)


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    await service.delete_organization(current_user=current_user, organization_id=organization_id)


@router.get("/{organization_id}/members", response_model=list[MemberRead])
async def list_members(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> list[MemberRead]:
    members = await service.list_members(current_user=current_user, organization_id=organization_id)
    return [_member_to_read(m) for m in members]


@router.post(
    "/{organization_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED
)
async def add_member(
    organization_id: UUID,
    payload: MemberAdd,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> MemberRead:
    membership = await service.add_member(
        current_user=current_user,
        organization_id=organization_id,
        email=payload.email,
        role=payload.role,
    )
    return _member_to_read(membership)


@router.patch("/{organization_id}/members/{user_id}", response_model=MemberRead)
async def update_member_role(
    organization_id: UUID,
    user_id: UUID,
    payload: MemberRoleUpdate,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> MemberRead:
    membership = await service.update_member_role(
        current_user=current_user,
        organization_id=organization_id,
        target_user_id=user_id,
        role=payload.role,
    )
    return _member_to_read(membership)


@router.delete("/{organization_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_member(
    organization_id: UUID,
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    service: OrganizationService = Depends(get_organization_service),
) -> None:
    await service.remove_member(
        current_user=current_user, organization_id=organization_id, target_user_id=user_id
    )