import logging

import pytest
from agentforge.config.settings import Settings
from agentforge.main import create_app
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel


def make_test_app() -> FastAPI:
    return create_app(Settings(_env_file=None, app_env="test"))


def test_health_reports_liveness() -> None:
    with TestClient(make_test_app()) as client:
        response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "agentforge-api",
        "version": "v1",
        "checks": {"liveness": "ok"},
    }


def test_readiness_is_separate_from_liveness() -> None:
    with TestClient(make_test_app()) as client:
        response = client.get("/api/v1/ready")

    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["checks"] == {"application": "ready"}


def test_settings_load_environment_and_validate_cors_origins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("LOG_LEVEL", "debug")
    monkeypatch.setenv("CORS_ORIGINS", '["https://dashboard.example"]')

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.log_level == "DEBUG"
    assert settings.cors_origins == ["https://dashboard.example"]


@pytest.mark.parametrize(
    "cors_origins",
    [["*"], ["https://dashboard.example/path"], ["https://user:password@example.com"]],
)
def test_settings_reject_non_origin_cors_values(cors_origins: list[str]) -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, cors_origins=cors_origins)


def test_validation_error_does_not_echo_submitted_values() -> None:
    class Payload(BaseModel):
        count: int

    application = make_test_app()

    @application.post("/test-validation")
    def validate_payload(payload: Payload) -> Payload:
        return payload

    secret_prompt = "private prompt content"
    with TestClient(application) as client:
        response = client.post("/test-validation", json={"count": secret_prompt})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert secret_prompt not in response.text


def test_not_found_uses_standard_error_response() -> None:
    with TestClient(make_test_app()) as client:
        response = client.get("/api/v1/missing")

    assert response.status_code == 404
    assert response.json() == {
        "error": {
            "code": "not_found",
            "message": "The requested resource was not found.",
            "details": [],
        }
    }


def test_unhandled_error_is_sanitized_in_response_and_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    application = make_test_app()
    secret_prompt = "private prompt content"

    @application.get("/test-error")
    def raise_error() -> None:
        raise RuntimeError(secret_prompt)

    with TestClient(application, raise_server_exceptions=False) as client:
        with caplog.at_level(logging.ERROR):
            response = client.get("/test-error")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert secret_prompt not in response.text
    assert secret_prompt not in caplog.text


def test_cors_allows_only_configured_origins() -> None:
    application = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            cors_origins=["https://dashboard.example"],
        )
    )

    with TestClient(application) as client:
        allowed = client.get(
            "/api/v1/health",
            headers={"Origin": "https://dashboard.example"},
        )
        denied = client.get(
            "/api/v1/health",
            headers={"Origin": "https://other.example"},
        )

    assert allowed.headers["access-control-allow-origin"] == "https://dashboard.example"
    assert "access-control-allow-origin" not in denied.headers
