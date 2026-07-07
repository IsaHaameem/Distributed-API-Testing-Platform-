"""Schedule endpoints.

Create/list are nested under a collection (/collections/{id}/schedules);
get/update/delete address a schedule directly by its own id
(/schedules/{id}), matching every other resource so far.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.schedule import Schedule
from app.models.user import User
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.repositories.schedule_repository import ScheduleRepository
from app.schemas.schedule import ScheduleCreate, ScheduleRead, ScheduleUpdate
from app.services.schedule_service import ScheduleService

router = APIRouter(tags=["schedules"])


def get_schedule_service(db: AsyncSession = Depends(get_db)) -> ScheduleService:
    return ScheduleService(
        ScheduleRepository(db),
        CollectionRepository(db),
        ProjectRepository(db),
        OrganizationMemberRepository(db),
    )


@router.post(
    "/collections/{collection_id}/schedules",
    response_model=ScheduleRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_schedule(
    collection_id: UUID,
    payload: ScheduleCreate,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> Schedule:
    return await service.create_schedule(
        current_user=current_user,
        collection_id=collection_id,
        cron_expression=payload.cron_expression,
        timezone_name=payload.timezone,
        is_active=payload.is_active,
    )


@router.get("/collections/{collection_id}/schedules", response_model=list[ScheduleRead])
async def list_schedules(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> list[Schedule]:
    return await service.list_schedules(current_user=current_user, collection_id=collection_id)


@router.get("/schedules/{schedule_id}", response_model=ScheduleRead)
async def get_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> Schedule:
    return await service.get_schedule(current_user=current_user, schedule_id=schedule_id)


@router.patch("/schedules/{schedule_id}", response_model=ScheduleRead)
async def update_schedule(
    schedule_id: UUID,
    payload: ScheduleUpdate,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> Schedule:
    fields = payload.model_dump(exclude_unset=True)
    return await service.update_schedule(
        current_user=current_user, schedule_id=schedule_id, fields=fields
    )


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ScheduleService = Depends(get_schedule_service),
) -> None:
    await service.delete_schedule(current_user=current_user, schedule_id=schedule_id)