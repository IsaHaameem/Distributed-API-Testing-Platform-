"""Schedule business logic. Authorization is inherited from the parent
collection -> project -> organization, same chain as API requests.

next_run_at is entirely system-computed: non-null if and only if the
schedule is currently active, so nothing reading this row has to
cross-reference is_active separately to know whether it will actually fire.
"""

from uuid import UUID

from app.core.exceptions import CollectionNotFoundError, ScheduleNotFoundError
from app.models.enums import OrganizationRole
from app.models.schedule import Schedule
from app.models.user import User
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.services.authorization import ADMIN_ROLES, organization_id_for_collection, require_membership
from app.services.cron import compute_next_run_at


class ScheduleService:
    def __init__(
        self,
        schedule_repository: ScheduleRepository,
        collection_repository: CollectionRepository,
        project_repository: ProjectRepository,
        member_repository: OrganizationMemberRepository,
    ) -> None:
        self.schedule_repository = schedule_repository
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

    async def _get_authorized_schedule(
        self,
        current_user: User,
        schedule_id: UUID,
        allowed_roles: set[OrganizationRole] | None = None,
    ) -> Schedule:
        schedule = await self.schedule_repository.get_by_id(schedule_id)
        if schedule is None:
            raise ScheduleNotFoundError()

        organization_id = await organization_id_for_collection(
            self.collection_repository,
            self.project_repository,
            schedule.collection_id,
            ScheduleNotFoundError,
        )
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            allowed_roles,
            not_found_error=ScheduleNotFoundError,
        )
        return schedule

    async def create_schedule(
        self,
        *,
        current_user: User,
        collection_id: UUID,
        cron_expression: str,
        timezone_name: str,
        is_active: bool,
    ) -> Schedule:
        organization_id = await self._organization_id_for_collection(collection_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )

        next_run_at = compute_next_run_at(cron_expression, timezone_name) if is_active else None

        return await self.schedule_repository.create(
            collection_id=collection_id,
            created_by=current_user.id,
            cron_expression=cron_expression,
            timezone=timezone_name,
            is_active=is_active,
            next_run_at=next_run_at,
        )

    async def list_schedules(self, *, current_user: User, collection_id: UUID) -> list[Schedule]:
        organization_id = await self._organization_id_for_collection(collection_id)
        await require_membership(
            self.member_repository,
            organization_id,
            current_user.id,
            not_found_error=CollectionNotFoundError,
        )
        return await self.schedule_repository.list_by_collection(collection_id)

    async def get_schedule(self, *, current_user: User, schedule_id: UUID) -> Schedule:
        return await self._get_authorized_schedule(current_user, schedule_id)

    async def update_schedule(
        self, *, current_user: User, schedule_id: UUID, fields: dict
    ) -> Schedule:
        schedule = await self._get_authorized_schedule(current_user, schedule_id)

        if "cron_expression" in fields or "timezone" in fields or "is_active" in fields:
            cron_expression = fields.get("cron_expression", schedule.cron_expression)
            timezone_name = fields.get("timezone", schedule.timezone)
            is_active = fields.get("is_active", schedule.is_active)
            fields["next_run_at"] = (
                compute_next_run_at(cron_expression, timezone_name) if is_active else None
            )

        return await self.schedule_repository.update(schedule, **fields)

    async def delete_schedule(self, *, current_user: User, schedule_id: UUID) -> None:
        schedule = await self._get_authorized_schedule(current_user, schedule_id, ADMIN_ROLES)
        await self.schedule_repository.delete(schedule)