"""Collection endpoints.

Create/list are nested under a project (/projects/{id}/collections);
get/update/delete address a collection directly by its own id
(/collections/{id}), matching the same pattern used for projects.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.collection import Collection
from app.models.user import User
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.collection import CollectionCreate, CollectionRead, CollectionUpdate
from app.services.collection_service import CollectionService

router = APIRouter(tags=["collections"])


def get_collection_service(db: AsyncSession = Depends(get_db)) -> CollectionService:
    return CollectionService(
        CollectionRepository(db), ProjectRepository(db), OrganizationMemberRepository(db)
    )


@router.post(
    "/projects/{project_id}/collections",
    response_model=CollectionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_collection(
    project_id: UUID,
    payload: CollectionCreate,
    current_user: User = Depends(get_current_user),
    service: CollectionService = Depends(get_collection_service),
) -> Collection:
    return await service.create_collection(
        current_user=current_user,
        project_id=project_id,
        name=payload.name,
        description=payload.description,
    )


@router.get("/projects/{project_id}/collections", response_model=list[CollectionRead])
async def list_collections(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CollectionService = Depends(get_collection_service),
) -> list[Collection]:
    return await service.list_collections(current_user=current_user, project_id=project_id)


@router.get("/collections/{collection_id}", response_model=CollectionRead)
async def get_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CollectionService = Depends(get_collection_service),
) -> Collection:
    return await service.get_collection(current_user=current_user, collection_id=collection_id)


@router.patch("/collections/{collection_id}", response_model=CollectionRead)
async def update_collection(
    collection_id: UUID,
    payload: CollectionUpdate,
    current_user: User = Depends(get_current_user),
    service: CollectionService = Depends(get_collection_service),
) -> Collection:
    update_data = payload.model_dump(exclude_unset=True)
    return await service.update_collection(
        current_user=current_user, collection_id=collection_id, update_data=update_data
    )


@router.delete("/collections/{collection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_collection(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    service: CollectionService = Depends(get_collection_service),
) -> None:
    await service.delete_collection(current_user=current_user, collection_id=collection_id)