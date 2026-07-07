"""Project endpoints.

Create/list are nested under an organization (/organizations/{id}/projects);
get/update/delete address a project directly by its own id (/projects/{id}),
since a project id alone is enough to resolve it and its authorization
without repeating the organization id in the path.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.project import Project
from app.models.user import User
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.project import ProjectCreate, ProjectRead, ProjectUpdate
from app.services.project_service import ProjectService

router = APIRouter(tags=["projects"])


def get_project_service(db: AsyncSession = Depends(get_db)) -> ProjectService:
    return ProjectService(ProjectRepository(db), OrganizationMemberRepository(db))


@router.post(
    "/organizations/{organization_id}/projects",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_project(
    organization_id: UUID,
    payload: ProjectCreate,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> Project:
    return await service.create_project(
        current_user=current_user,
        organization_id=organization_id,
        name=payload.name,
        description=payload.description,
    )


@router.get("/organizations/{organization_id}/projects", response_model=list[ProjectRead])
async def list_projects(
    organization_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> list[Project]:
    return await service.list_projects(current_user=current_user, organization_id=organization_id)


@router.get("/projects/{project_id}", response_model=ProjectRead)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> Project:
    return await service.get_project(current_user=current_user, project_id=project_id)


@router.patch("/projects/{project_id}", response_model=ProjectRead)
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> Project:
    update_data = payload.model_dump(exclude_unset=True)
    return await service.update_project(
        current_user=current_user, project_id=project_id, update_data=update_data
    )


@router.delete("/projects/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ProjectService = Depends(get_project_service),
) -> None:
    await service.delete_project(current_user=current_user, project_id=project_id)