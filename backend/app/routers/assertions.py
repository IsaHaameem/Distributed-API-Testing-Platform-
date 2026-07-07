"""Assertion endpoints. Create/list under a request; delete by the
assertion's own id. No update -- see the milestone notes on why."""

from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.assertion import Assertion
from app.models.user import User
from app.repositories.api_request_repository import ApiRequestRepository
from app.repositories.assertion_repository import AssertionRepository
from app.repositories.collection_repository import CollectionRepository
from app.repositories.organization_member_repository import OrganizationMemberRepository
from app.repositories.project_repository import ProjectRepository
from app.schemas.assertion import AssertionCreate, AssertionRead
from app.services.assertion_service import AssertionService

router = APIRouter(tags=["assertions"])


def get_assertion_service(db: AsyncSession = Depends(get_db)) -> AssertionService:
    return AssertionService(
        AssertionRepository(db),
        ApiRequestRepository(db),
        CollectionRepository(db),
        ProjectRepository(db),
        OrganizationMemberRepository(db),
    )


@router.post(
    "/requests/{request_id}/assertions",
    response_model=AssertionRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_assertion(
    request_id: UUID,
    payload: AssertionCreate,
    current_user: User = Depends(get_current_user),
    service: AssertionService = Depends(get_assertion_service),
) -> Assertion:
    return await service.create_assertion(
        current_user=current_user,
        api_request_id=request_id,
        type_=payload.type,
        config=payload.config.model_dump(),
    )


@router.get("/requests/{request_id}/assertions", response_model=list[AssertionRead])
async def list_assertions(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AssertionService = Depends(get_assertion_service),
) -> list[Assertion]:
    return await service.list_assertions(current_user=current_user, api_request_id=request_id)


@router.delete("/assertions/{assertion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assertion(
    assertion_id: UUID,
    current_user: User = Depends(get_current_user),
    service: AssertionService = Depends(get_assertion_service),
) -> None:
    await service.delete_assertion(current_user=current_user, assertion_id=assertion_id)