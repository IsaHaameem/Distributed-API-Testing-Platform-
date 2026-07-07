"""Authentication endpoints: register, login, current-user lookup."""

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user, get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository
from app.schemas.user import Token, UserRead, UserRegister
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["auth"])


def get_auth_service(db: AsyncSession = Depends(get_db)) -> AuthService:
    return AuthService(UserRepository(db))


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: UserRegister,
    auth_service: AuthService = Depends(get_auth_service),
) -> User:
    return await auth_service.register(
        email=payload.email, password=payload.password, full_name=payload.full_name
    )


@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    auth_service: AuthService = Depends(get_auth_service),
) -> Token:
    user = await auth_service.authenticate(email=form_data.username, password=form_data.password)
    access_token = auth_service.issue_token(user)
    return Token(access_token=access_token)


@router.get("/me", response_model=UserRead)
async def read_current_user(current_user: User = Depends(get_current_user)) -> User:
    return current_user