"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import get_settings
from app.core.logging_config import setup_logging
from app.database import engine
from app.middlewares.logging_middleware import LoggingMiddleware
from app.routers import health

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging(settings.log_level)
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    """Build and configure the FastAPI application."""
    application = FastAPI(
        title="Distributed API Testing & Monitoring Platform",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.add_middleware(LoggingMiddleware)
    application.include_router(health.router)

    return application


app = create_app()