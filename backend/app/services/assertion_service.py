"""Assertion business logic. Authorization is inherited through the parent
request -> collection -> project -> organization chain."""

from uuid import UUID

from app.core.exceptions import ApiRequestNotFoundError, AssertionNotFoundError
from app.models.assertion import Assertion
from app.models.user import User
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.assertion_repository import AssertionRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.services.authorization import ADMIN_ROLES, organization_id_for_collection, require_membership


class AssertionService:
    def __init__(
        self,
        assertion_repository: AssertionRepository,
        request_repository: ApiRequestRepository,
        collection_repository: CollectionRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
        self.assertion_repository = assertion_repository
        self.request_repository = request_repository
        self.collection_repository = collection_repository
        self.project_repository = project_repository
        self.member_repository = member_repository

    async def _organization_id_for_request(self, api_request_id: UUID) -> UUID:
        request = await self.request_repository.get_by_id(api_request_id)
        if request is None:
            raise ApiRequestNotFoundError()
        return await organization_id_for_collection(
            self.collection_repository,
            self.project_repository,
            request.collection_id,
            ApiRequestNotFoundError,
        )

    async def create_assertion(
        self, *, current_user: User, api_request_id: UUID, type_: str, config: dict
    ) -> Assertion:
        organization_id = await self._organization_id_for_request(api_request_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=ApiRequestNotFoundError,
        )
        return await self.assertion_repository.create(
            api_request_id=api_request_id, type_=type_, config=config
        )

    async def list_assertions(self, *, current_user: User, api_request_id: UUID) -> list[Assertion]:
        organization_id = await self._organization_id_for_request(api_request_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=ApiRequestNotFoundError,
        )
        return await self.assertion_repository.list_by_request(api_request_id)

    async def delete_assertion(self, *, current_user: User, assertion_id: UUID) -> None:
        assertion = await self.assertion_repository.get_by_id(assertion_id)
        if assertion is None:
            raise AssertionNotFoundError()

        organization_id = await self._organization_id_for_request(assertion.api_request_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            ADMIN_ROLES,
            not_found_error=AssertionNotFoundError,
        )
        await self.assertion_repository.delete(assertion)