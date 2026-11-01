"""Environment-backed application settings."""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Settings shared by the API application."""

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)
    database_url: str = "postgresql+psycopg://localhost/agentforge"
    test_database_url: str = "postgresql+psycopg://localhost/agentforge_test"

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized = value.upper()
        if normalized not in {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}:
            raise ValueError("LOG_LEVEL must be a standard logging level")
        return normalized

    @field_validator("cors_origins")
    @classmethod
    def validate_cors_origins(cls, origins: list[str]) -> list[str]:
        normalized_origins = []
        for origin in origins:
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or parsed.username
                or parsed.password
            ):
                raise ValueError("CORS_ORIGINS must contain only HTTP(S) origins")
            try:
                parsed.port
            except ValueError as exc:
                raise ValueError("CORS_ORIGINS contains an invalid port") from exc
            normalized_origins.append(origin.rstrip("/"))
        return normalized_origins

    @field_validator("database_url", "test_database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        try:
            url = make_url(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("Database URLs must be valid PostgreSQL URLs") from exc
        if url.drivername != "postgresql+psycopg" or not url.database:
            raise ValueError("Database URLs must use PostgreSQL with the psycopg driver")
        return value

    @property
    def runtime_database_url(self) -> str:
        """Select an isolated database when the application is running in tests."""
        if self.app_env.casefold() == "test":
            return self.test_database_url
        return self.database_url
