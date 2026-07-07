"""Environment variable endpoints.

Create/list are nested under a project (/projects/{id}/environment-variables);
get/update/delete address a variable directly by its own id
(/environment-variables/{id}), matching every other resource so far.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.environment_variable import EnvironmentVariable
from app.models.user import User
from app.repositories.environment_variable_repository import EnvironmentVariableRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.environment_variable import (
    EnvironmentVariableCreate,
    EnvironmentVariableRead,
    EnvironmentVariableUpdate,
)
from app.services.environment_variable_service import EnvironmentVariableService

router = APIRouter(tags=["environment-variables"])


def get_environment_variable_service(
    db: AsyncSession = Depends(get_db),
) -> EnvironmentVariableService:
    return EnvironmentVariableService(
        EnvironmentVariableRepository(db), ProjectRepository(db), OrganizationMemberRepository(db)
    )


@router.post(
    "/projects/{project_id}/environment-variables",
    response_model=EnvironmentVariableRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_variable(
    project_id: UUID,
    payload: EnvironmentVariableCreate,
    current_user: User = Depends(get_current_user),
    service: EnvironmentVariableService = Depends(get_environment_variable_service),
) -> EnvironmentVariable:
    return await service.create_variable(
        current_user=current_user,
        project_id=project_id,
        key=payload.key,
        value=payload.value,
        is_secret=payload.is_secret,
    )


@router.get(
    "/projects/{project_id}/environment-variables", response_model=list[EnvironmentVariableRead]
)
async def list_variables(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: EnvironmentVariableService = Depends(get_environment_variable_service),
) -> list[EnvironmentVariable]:
    return await service.list_variables(current_user=current_user, project_id=project_id)


@router.get("/environment-variables/{variable_id}", response_model=EnvironmentVariableRead)
async def get_variable(
    variable_id: UUID,
    current_user: User = Depends(get_current_user),
    service: EnvironmentVariableService = Depends(get_environment_variable_service),
) -> EnvironmentVariable:
    return await service.get_variable(current_user=current_user, variable_id=variable_id)


@router.patch("/environment-variables/{variable_id}", response_model=EnvironmentVariableRead)
async def update_variable(
    variable_id: UUID,
    payload: EnvironmentVariableUpdate,
    current_user: User = Depends(get_current_user),
    service: EnvironmentVariableService = Depends(get_environment_variable_service),
) -> EnvironmentVariable:
    fields = payload.model_dump(exclude_unset=True)
    return await service.update_variable(
        current_user=current_user, variable_id=variable_id, fields=fields
    )


@router.delete("/environment-variables/{variable_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variable(
    variable_id: UUID,
    current_user: User = Depends(get_current_user),
    service: EnvironmentVariableService = Depends(get_environment_variable_service),
) -> None:
    await service.delete_variable(current_user=current_user, variable_id=variable_id)