"""API request endpoints.

Create/list are nested under a collection (/collections/{id}/requests);
get/update/delete address a request directly by its own id (/requests/{id}),
matching the pattern used for projects and collections.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.api_request import ApiRequest
from app.models.user import User
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.api_request import ApiRequestCreate, ApiRequestRead, ApiRequestUpdate
from app.services.api_request_service import ApiRequestService

router = APIRouter(tags=["requests"])


def get_api_request_service(db: AsyncSession = Depends(get_db)) -> ApiRequestService:
    return ApiRequestService(
        ApiRequestRepository(db),
        CollectionRepository(db),
        ProjectRepository(db),
        OrganizationMemberRepository(db),
    )


@router.post(
    "/collections/{collection_id}/requests",
    response_model=ApiRequestRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_request(
    collection_id: UUID,
    payload: ApiRequestCreate,
    current_user: User = Depends(get_current_user),
    service: ApiRequestService = Depends(get_api_request_service),
) -> ApiRequest:
    return await service.create_request(
        current_user=current_user, collection_id=collection_id, fields=payload.model_dump()
    )


@router.get("/collections/{collection_id}/requests", response_model=list[ApiRequestRead])
async def list_requests(
    collection_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ApiRequestService = Depends(get_api_request_service),
) -> list[ApiRequest]:
    return await service.list_requests(current_user=current_user, collection_id=collection_id)


@router.get("/requests/{request_id}", response_model=ApiRequestRead)
async def get_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ApiRequestService = Depends(get_api_request_service),
) -> ApiRequest:
    return await service.get_request(current_user=current_user, request_id=request_id)


@router.patch("/requests/{request_id}", response_model=ApiRequestRead)
async def update_request(
    request_id: UUID,
    payload: ApiRequestUpdate,
    current_user: User = Depends(get_current_user),
    service: ApiRequestService = Depends(get_api_request_service),
) -> ApiRequest:
    fields = payload.model_dump(exclude_unset=True)
    return await service.update_request(current_user=current_user, request_id=request_id, fields=fields)


@router.delete("/requests/{request_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: ApiRequestService = Depends(get_api_request_service),
) -> None:
    await service.delete_request(current_user=current_user, request_id=request_id)