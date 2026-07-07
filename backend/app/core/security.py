"""Password hashing and JWT issuance/verification."""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import get_settings
from app.core.exceptions import InvalidTokenError

settings = get_settings()

# OWASP-current parameters for Argon2id (time_cost, memory_cost in KiB, parallelism).
_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=1)


def hash_password(password: str) -> str:
    """Hash a plaintext password with Argon2id."""
    return _password_hasher.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2 hash. Never raises."""
    try:
        return _password_hasher.verify(hashed_password, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def create_access_token(subject: UUID) -> str:
    """Issue a signed JWT access token identifying the given user."""
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)

    payload = {
        "sub": str(subject),
        "iat": now,
        "exp": expires_at,
        "jti": str(uuid4()),
    }

    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token. Raises InvalidTokenError on any failure."""
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise InvalidTokenError() from exc