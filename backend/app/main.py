"""FastAPI application factory."""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging_config import setup_logging
from app.core.redis_client import get_redis_client
from app.database import engine
from app.middlewares.logging_middleware import LoggingMiddleware
from app.queue.constants import TASK_STREAM_NAME, WORKER_CONSUMER_GROUP
from app.queue.retry_queue import RetryQueue
from app.queue.stream_client import StreamQueue
from app.routers import (
    assertions,
    auth,
    collections,
    environment_variables,
    health,
    organizations,
    projects,
    requests,
    runs,
    schedules,
    workers,
)
from scheduler.retry_sweeper import RetrySweeper

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)

    redis_client = get_redis_client()
    stream_queue = StreamQueue(redis_client, TASK_STREAM_NAME, WORKER_CONSUMER_GROUP)
    retry_sweeper = RetrySweeper(
        RetryQueue(redis_client),
        stream_queue,
        interval_seconds=settings.retry_sweep_interval_seconds,
    )
    shutdown_event = asyncio.Event()
    sweep_task = asyncio.create_task(retry_sweeper.run_forever(shutdown_event))

    yield

    shutdown_event.set()
    await sweep_task
    await redis_client.aclose()
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title="Distributed API Testing & Monitoring Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(LoggingMiddleware)

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers=exc.headers,
        )

    application.include_router(health.router)
    application.include_router(auth.router)
    application.include_router(organizations.router)
    application.include_router(projects.router)
    application.include_router(collections.router)
    application.include_router(requests.router)
    application.include_router(assertions.router)
    application.include_router(environment_variables.router)
    application.include_router(schedules.router)
    application.include_router(workers.router)
    application.include_router(runs.router)

    return application


app = create_app()