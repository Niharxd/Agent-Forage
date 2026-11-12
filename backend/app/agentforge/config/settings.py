"""Environment-backed application settings."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

PROJECT_ROOT = Path(__file__).resolve().parents[4]


class Settings(BaseSettings):
    """Settings shared by the API application."""

    app_env: str = "development"
    log_level: str = "INFO"
    cors_origins: list[str] = Field(default_factory=list)
    provider_mode: Literal["mock", "openai"] = "mock"
    openai_api_key: SecretStr | None = None
    openai_model: str = Field(default="gpt-4o-mini", min_length=1, max_length=100)
    openai_timeout_seconds: float = Field(default=30, gt=0, le=60)
    api_access_token: SecretStr | None = None
    database_url: str = "postgresql+psycopg://localhost/agentforge"
    test_database_url: str = "postgresql+psycopg://localhost/agentforge_test"
    workflow_max_tasks: int = Field(default=25, ge=1, le=25)
    workflow_max_execution_steps: int = Field(default=25, ge=1, le=25)
    workflow_max_task_input_bytes: int = Field(default=10_000, ge=1, le=10_000)
    workflow_max_result_bytes: int = Field(default=100_000, ge=1, le=1_000_000)
    workflow_history_size: int = Field(default=100, ge=1, le=10_000)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_provider_settings(self) -> "Settings":
        if self.provider_mode == "openai" and (
            self.openai_api_key is None or not self.openai_api_key.get_secret_value().strip()
        ):
            raise ValueError("OPENAI_API_KEY is required when PROVIDER_MODE is openai")
        if self.provider_mode == "openai" and (
            self.api_access_token is None or not self.api_access_token.get_secret_value().strip()
        ):
            raise ValueError("API_ACCESS_TOKEN is required when PROVIDER_MODE is openai")
        return self

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
