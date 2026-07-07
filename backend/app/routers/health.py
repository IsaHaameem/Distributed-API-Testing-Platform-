"""Health check endpoint — verifies the process is up AND its dependencies are reachable."""

from fastapi import APIRouter, Depends, Response, status
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_db, get_redis

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check(
    response: Response,
    db: AsyncSession = Depends(get_db),
    redis_client: Redis = Depends(get_redis),
) -> dict:
    """Return the status of the API process and its direct dependencies."""
    db_status = "ok"
    redis_status = "ok"

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "unavailable"

    try:
        await redis_client.ping()
    except Exception:
        redis_status = "unavailable"

    healthy = db_status == "ok" and redis_status == "ok"
    response.status_code = (
        status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE
    )

    return {
        "status": "ok" if healthy else "degraded",
        "database": db_status,
        "redis": redis_status,
    }