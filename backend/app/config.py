"""Application configuration, loaded from environment variables / .env."""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "development"
    log_level: str = "INFO"

    database_url: str
    redis_url: str

    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60

    worker_capacity: int = 10
    worker_heartbeat_interval_seconds: int = 5

    retry_sweep_interval_seconds: int = 2


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()