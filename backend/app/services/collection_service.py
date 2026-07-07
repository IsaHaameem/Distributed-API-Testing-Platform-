"""Collection business logic. Like projects, authorization is inherited --
through the parent project's organization -- with no per-collection ACL."""

from uuid import UUID

from app.core.exceptions import CollectionNotFoundError, ProjectNotFoundError
from app.models.collection import Collection
from app.models.enums import OrganizationRole
from app.models.project import Project
from app.models.user import User
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.services.authorization import ADMIN_ROLES, require_membership


class CollectionService:
    def __init__(
        self,
        collection_repository: CollectionRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
        self.collection_repository = collection_repository
        self.project_repository = project_repository
        self.member_repository = member_repository

    async def _get_authorized_project(
        self,
        current_user: User,
        project_id: UUID,
        allowed_roles: set[OrganizationRole] | None = None,
    ) -> Project:
        project = await self.project_repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError()
        await require_membership(
            self.member_repository,
            project.organization_id,
            current_user.id,
            allowed_roles,
            not_found_error=ProjectNotFoundError,
        )
        return project

    async def _get_authorized_collection(
        self,
        current_user: User,
        collection_id: UUID,
        allowed_roles: set[OrganizationRole] | None = None,
    ) -> Collection:
        collection = await self.collection_repository.get_by_id(collection_id)
        if collection is None:
            raise CollectionNotFoundError()

        project = await self.project_repository.get_by_id(collection.project_id)
        if project is None:
            raise CollectionNotFoundError()

        await require_membership(
            self.member_repository,
            project.organization_id,
            current_user.id,
            allowed_roles,
            not_found_error=CollectionNotFoundError,
        )
        return collection

    async def create_collection(
        self, *, current_user: User, project_id: UUID, name: str, description: str | None
    ) -> Collection:
        await self._get_authorized_project(current_user, project_id)
        return await self.collection_repository.create(
            project_id=project_id, name=name, description=description
        )

    async def list_collections(self, *, current_user: User, project_id: UUID) -> list[Collection]:
        await self._get_authorized_project(current_user, project_id)
        return await self.collection_repository.list_by_project(project_id)

    async def get_collection(self, *, current_user: User, collection_id: UUID) -> Collection:
        return await self._get_authorized_collection(current_user, collection_id)

    async def update_collection(
        self, *, current_user: User, collection_id: UUID, update_data: dict
    ) -> Collection:
        collection = await self._get_authorized_collection(current_user, collection_id)
        return await self.collection_repository.update(collection, **update_data)

    async def delete_collection(self, *, current_user: User, collection_id: UUID) -> None:
        collection = await self._get_authorized_collection(current_user, collection_id, ADMIN_ROLES)
        await self.collection_repository.delete(collection)