"""Shared organization-membership authorization checks, used by every service
that operates on organization-scoped resources."""

from uuid import UUID

from app.core.exceptions import AppError, InsufficientPermissionsError, OrganizationNotFoundError
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.repositories.organization_member_repository import OrganizationMemberRepository

ADMIN_ROLES = {OrganizationRole.OWNER, OrganizationRole.ADMIN}


async def require_membership(
    member_repository: OrganizationMemberRepository,
    organization_id: UUID,
    user_id: UUID,
    allowed_roles: set[OrganizationRole] | None = None,
    not_found_error: type[AppError] = OrganizationNotFoundError,
) -> OrganizationMember:
    """Return the caller's membership in an organization, or raise.

    A non-member gets the same not-found error a nonexistent resource would --
    membership is never leaked to people outside it. `not_found_error` lets
    each caller match the error to whatever the URL is actually about (a
    project lookup should 404 as "project not found", not "organization
    not found", even though the underlying check is identical).
    """
    membership = await member_repository.get_membership(organization_id, user_id)
    if membership is None:
        raise not_found_error()
    if allowed_roles is not None and membership.role not in allowed_roles:
        raise InsufficientPermissionsError()
    return membership