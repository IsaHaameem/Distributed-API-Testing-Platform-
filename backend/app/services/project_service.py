"""Project business logic. A project's authorization is entirely inherited
from its parent organization -- there is no per-project ACL."""

from uuid import UUID

from app.core.exceptions import ProjectNotFoundError
from app.models.enums import OrganizationRole
from app.models.project import Project
from app.models.user import User
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.services.authorization import ADMIN_ROLES, require_membership


class ProjectService:
    def __init__(
        self,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
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

    async def create_project(
        self, *, current_user: User, organization_id: UUID, name: str, description: str | None
    ) -> Project:
        await require_membership(self.member_repository, organization_id, current_user.id)
        return await self.project_repository.create(
            organization_id=organization_id,
            name=name,
            description=description,
            created_by=current_user.id,
        )

    async def list_projects(self, *, current_user: User, organization_id: UUID) -> list[Project]:
        await require_membership(self.member_repository, organization_id, current_user.id)
        return await self.project_repository.list_by_organization(organization_id)

    async def get_project(self, *, current_user: User, project_id: UUID) -> Project:
        return await self._get_authorized_project(current_user, project_id)

    async def update_project(
        self, *, current_user: User, project_id: UUID, update_data: dict
    ) -> Project:
        project = await self._get_authorized_project(current_user, project_id)
        return await self.project_repository.update(project, **update_data)

    async def delete_project(self, *, current_user: User, project_id: UUID) -> None:
        project = await self._get_authorized_project(current_user, project_id, ADMIN_ROLES)
        await self.project_repository.delete(project)