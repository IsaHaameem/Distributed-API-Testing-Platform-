"""FastAPI application factory."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import AppError
from app.core.logging_config import setup_logging
from app.database import engine
from app.middlewares.logging_middleware import LoggingMiddleware
from app.routers import auth, collections, health, organizations, projects

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

    return application


app = create_app()