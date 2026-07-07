"""Environment variable business logic. Authorization is inherited from the
parent project -> organization. On top of that, any operation that touches a
secret -- setting is_secret, changing the value of something already secret,
or changing the key/value of something being made secret -- requires
admin/owner, even though non-secret variables are open to any member."""

from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import (
    EnvironmentVariableKeyTakenError,
    EnvironmentVariableNotFoundError,
    InsufficientPermissionsError,
    ProjectNotFoundError,
)
from app.models.enums import OrganizationRole
from app.models.environment_variable import EnvironmentVariable
from app.models.user import User
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.services.authorization import ADMIN_ROLES, require_membership


class EnvironmentVariableService:
    def __init__(
        self,
        variable_repository: EnvironmentVariableRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
        self.variable_repository = variable_repository
        self.project_repository = project_repository
        self.member_repository = member_repository

    async def _organization_id_for_project(self, project_id: UUID) -> UUID:
        project = await self.project_repository.get_by_id(project_id)
        if project is None:
            raise ProjectNotFoundError()
        return project.organization_id

    async def _get_authorized_variable(
        self, current_user: User, variable_id: UUID
    ) -> tuple[EnvironmentVariable, OrganizationRole]:
        variable = await self.variable_repository.get_by_id(variable_id)
        if variable is None:
            raise EnvironmentVariableNotFoundError()

        organization_id = await self._organization_id_for_project(variable.project_id)
        membership = await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=EnvironmentVariableNotFoundError,
        )
        return variable, membership.role

    async def create_variable(
        self, *, current_user: User, project_id: UUID, key: str, value: str, is_secret: bool
    ) -> EnvironmentVariable:
        organization_id = await self._organization_id_for_project(project_id)
        membership = await require_membership(
            self.member_repository, organization_id, current_user.id, not_found_error=ProjectNotFoundError
        )

        if is_secret and membership.role not in ADMIN_ROLES:
            raise InsufficientPermissionsError()

        try:
            return await self.variable_repository.create(
                project_id=project_id, key=key, value=value, is_secret=is_secret
            )
        except IntegrityError as exc:
            raise EnvironmentVariableKeyTakenError() from exc

    async def list_variables(
        self, *, current_user: User, project_id: UUID
    ) -> list[EnvironmentVariable]:
        organization_id = await self._organization_id_for_project(project_id)
        await require_membership(
            self.member_repository, organization_id, current_user.id, not_found_error=ProjectNotFoundError
        )
        return await self.variable_repository.list_by_project(project_id)

    async def get_variable(self, *, current_user: User, variable_id: UUID) -> EnvironmentVariable:
        variable, _ = await self._get_authorized_variable(current_user, variable_id)
        return variable

    async def update_variable(
        self, *, current_user: User, variable_id: UUID, fields: dict
    ) -> EnvironmentVariable:
        variable, role = await self._get_authorized_variable(current_user, variable_id)

        becoming_secret = fields.get("is_secret", variable.is_secret)
        if (variable.is_secret or becoming_secret) and role not in ADMIN_ROLES:
            raise InsufficientPermissionsError()

        try:
            return await self.variable_repository.update(variable, **fields)
        except IntegrityError as exc:
            raise EnvironmentVariableKeyTakenError() from exc

    async def delete_variable(self, *, current_user: User, variable_id: UUID) -> None:
        variable, role = await self._get_authorized_variable(current_user, variable_id)
        if role not in ADMIN_ROLES:
            raise InsufficientPermissionsError()
        await self.variable_repository.delete(variable)