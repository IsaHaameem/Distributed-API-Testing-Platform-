"""Authentication business logic."""

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import EmailAlreadyRegisteredError, InactiveUserError, InvalidCredentialsError
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User
from app.repositories.user_repository import UserRepository

# Hashed once at import time and reused so that a login attempt against a
# nonexistent email still pays the same Argon2 cost as a real one — otherwise
# the response-time difference becomes a way to enumerate registered emails.
_DUMMY_HASH = hash_password("a-placeholder-password-used-only-for-timing-safety")


class AuthService:
    def __init__(self, user_repository: UserRepository) -> None:
        self.user_repository = user_repository

    async def register(self, *, email: str, password: str, full_name: str) -> User:
        normalized_email = email.strip().lower()

        existing_user = await self.user_repository.get_by_email(normalized_email)
        if existing_user is not None:
            raise EmailAlreadyRegisteredError()

        hashed_password = hash_password(password)
        try:
            return await self.user_repository.create(
                email=normalized_email,
                hashed_password=hashed_password,
                full_name=full_name.strip(),
            )
        except IntegrityError as exc:
            # Two concurrent registrations for the same email can both pass the
            # check above before either commits; the DB's unique constraint is
            # the real guard, this just turns that race into a clean 409.
            raise EmailAlreadyRegisteredError() from exc

    async def authenticate(self, *, email: str, password: str) -> User:
        normalized_email = email.strip().lower()

        user = await self.user_repository.get_by_email(normalized_email)
        if user is None:
            verify_password(password, _DUMMY_HASH)
            raise InvalidCredentialsError()

        if not verify_password(password, user.hashed_password):
            raise InvalidCredentialsError()

        if not user.is_active:
            raise InactiveUserError()

        return user

    def issue_token(self, user: User) -> str:
        return create_access_token(subject=user.id)