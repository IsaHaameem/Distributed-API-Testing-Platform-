"""API request business logic. Authorization is inherited from the parent
collection -> project -> organization chain, same as collections."""

from uuid import UUID

from app.core.exceptions import ApiRequestNotFoundError, CollectionNotFoundError
from app.models.api_request import ApiRequest
from app.models.enums import OrganizationRole
from app.models.user import User
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.services.authorization import ADMIN_ROLES, organization_id_for_collection, require_membership


class ApiRequestService:
    def __init__(
        self,
        request_repository: ApiRequestRepository,
        collection_repository: CollectionRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
        self.request_repository = request_repository
        self.collection_repository = collection_repository
        self.project_repository = project_repository
        self.member_repository = member_repository

    async def _organization_id_for_collection(self, collection_id: UUID) -> UUID:
        return await organization_id_for_collection(
            self.collection_repository,
            self.project_repository,
            collection_id,
            CollectionNotFoundError,
        )

    async def _get_authorized_request(
        self,
        current_user: User,
        request_id: UUID,
        allowed_roles: set[OrganizationRole] | None = None,
    ) -> ApiRequest:
        request = await self.request_repository.get_by_id(request_id)
        if request is None:
            raise ApiRequestNotFoundError()

        organization_id = await self._organization_id_for_collection(request.collection_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            allowed_roles,
            not_found_error=ApiRequestNotFoundError,
        )
        return request

    async def create_request(
        self, *, current_user: User, collection_id: UUID, fields: dict
    ) -> ApiRequest:
        organization_id = await self._organization_id_for_collection(collection_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )

        if fields.get("order_index") is None:
            existing = await self.request_repository.list_by_collection(collection_id)
            fields["order_index"] = len(existing)

        return await self.request_repository.create(collection_id=collection_id, **fields)

    async def list_requests(self, *, current_user: User, collection_id: UUID) -> list[ApiRequest]:
        organization_id = await self._organization_id_for_collection(collection_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )
        return await self.request_repository.list_by_collection(collection_id)

    async def get_request(self, *, current_user: User, request_id: UUID) -> ApiRequest:
        return await self._get_authorized_request(current_user, request_id)

    async def update_request(
        self, *, current_user: User, request_id: UUID, fields: dict
    ) -> ApiRequest:
        request = await self._get_authorized_request(current_user, request_id)
        return await self.request_repository.update(request, **fields)

    async def delete_request(self, *, current_user: User, request_id: UUID) -> None:
        request = await self._get_authorized_request(current_user, request_id, ADMIN_ROLES)
        await self.request_repository.delete(request)