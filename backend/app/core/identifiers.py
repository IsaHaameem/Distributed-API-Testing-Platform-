"""UUIDv7 primary key generation, shared by every ORM model."""

from uuid import UUID

from uuid6 import uuid7


def generate_uuid7() -> UUID:
    """Generate a time-ordered UUIDv7 for use as a primary key default."""
    return uuid7()