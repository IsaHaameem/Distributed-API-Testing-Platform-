"""Shared FastAPI dependencies. Routers should import Depends() targets from here."""

from collections.abc import AsyncGenerator
from uuid import UUID

from fastapi import Depends
from fastapi.security import OAuth2PasswordBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InactiveUserError, InvalidTokenError
from app.core.redis_client import get_redis_client
from app.core.security import decode_access_token
from app.database import get_db
from app.models.user import User
from app.repositories.user_repository import UserRepository

__all__ = ["get_db", "get_redis", "get_current_user"]

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/login")


async def get_redis() -> AsyncGenerator[Redis, None]:
    client = get_redis_client()
    try:
        yield client
    finally:
        await client.aclose()


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    payload = decode_access_token(token)

    raw_user_id = payload.get("sub")
    if raw_user_id is None:
        raise InvalidTokenError()

    try:
        user_id = UUID(raw_user_id)
    except (ValueError, TypeError) as exc:
        raise InvalidTokenError() from exc

    user_repository = UserRepository(db)
    user = await user_repository.get_by_id(user_id)
    if user is None:
        raise InvalidTokenError()

    if not user.is_active:
        raise InactiveUserError()

    return user