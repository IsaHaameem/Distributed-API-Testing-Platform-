"""Pydantic schema for worker observability."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import WorkerStatus


class WorkerRead(BaseModel):
    id: UUID
    hostname: str
    pid: int
    status: WorkerStatus
    capacity: int
    registered_at: datetime
    last_seen_at: datetime | None
    is_alive: bool