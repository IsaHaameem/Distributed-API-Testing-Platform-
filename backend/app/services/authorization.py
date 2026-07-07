"""Shared organization-membership authorization checks, used by every service
that operates on organization-scoped resources."""

from uuid import UUID

from app.core.exceptions import AppError, InsufficientPermissionsError, OrganizationNotFoundError
from app.models.enums import OrganizationRole
from app.models.organization_member import OrganizationMember
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository

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


async def organization_id_for_collection(
    collection_repository: CollectionRepository,
    project_repository: ProjectRepository,
    collection_id: UUID,
    not_found_error: type[AppError],
) -> UUID:
    """Resolve a collection's organization_id via its parent project.

    Shared by every service whose resource hangs directly off a collection
    (requests, schedules) -- previously duplicated per service, which is
    exactly the kind of drift require_membership was extracted to avoid.
    """
    collection = await collection_repository.get_by_id(collection_id)
    if collection is None:
        raise not_found_error()
    project = await project_repository.get_by_id(collection.project_id)
    if project is None:
        raise not_found_error()
    return project.organization_id