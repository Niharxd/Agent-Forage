"""Security checks for the browser operator session boundary."""

from agentforge.api import auth as auth_module
from agentforge.api.routes import executions as execution_routes
from agentforge.api.routes import workflows as workflow_routes
from agentforge.config.settings import Settings
from agentforge.main import create_app
from fastapi.testclient import TestClient
from pydantic import SecretStr

ORIGIN = "http://localhost:5173"


def client(*, token: str | None = "test-operator-secret", secret: str | None = "s" * 40):
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr(token) if token else None,
        session_signing_secret=SecretStr(secret) if secret else None,
    )
    return TestClient(create_app(settings))


def test_operator_login_restores_and_logs_out_session(monkeypatch) -> None:
    class ApprovalRepository:
        def __init__(self, _session):
            pass

        def get_execution(self, _execution_id):
            return object()

        def get_approval_requests(self, **_kwargs):
            return []

    monkeypatch.setattr(execution_routes, "ExecutionRepository", ApprovalRepository)
    with client() as test_client:
        login = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "test-operator-secret"},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        assert login.json()["authenticated"] is True
        assert isinstance(login.json()["expires_at"], int)
        cookie = test_client.cookies.get("agentforge_operator_session")
        assert cookie and "httponly" in login.headers["set-cookie"].lower()
        assert "test-operator-secret" not in login.text
        assert "s" * 40 not in login.text
        assert test_client.get("/api/v1/auth/session").status_code == 200
        assert (
            test_client.get(
                "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals"
            ).status_code
            == 200
        )
        logout = test_client.delete("/api/v1/auth/session", headers={"Origin": ORIGIN})
        assert logout.status_code == 204
        test_client.cookies.set("agentforge_operator_session", cookie)
        assert test_client.get("/api/v1/auth/session").status_code == 401


def test_tampered_and_expired_sessions_are_rejected(monkeypatch) -> None:
    with client() as test_client:
        test_client.post(
            "/api/v1/auth/session",
            json={"credential": "test-operator-secret"},
            headers={"Origin": ORIGIN},
        )
        token = test_client.cookies.get("agentforge_operator_session")
        assert token
        test_client.cookies.set("agentforge_operator_session", token + "tampered")
        assert test_client.get("/api/v1/auth/session").status_code == 401
        test_client.cookies.set("agentforge_operator_session", token)
        monkeypatch.setattr(auth_module.time, "time", lambda: 4_000_000_000)
        assert test_client.get("/api/v1/auth/session").status_code == 401


def test_invalid_credential_and_disallowed_origin_are_rejected() -> None:
    with client() as test_client:
        invalid = test_client.post(
            "/api/v1/auth/session", json={"credential": "wrong"}, headers={"Origin": ORIGIN}
        )
        assert invalid.status_code == 401
        denied = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "test-operator-secret"},
            headers={"Origin": "https://attacker.example"},
        )
        assert denied.status_code == 403
        missing = test_client.post("/api/v1/auth/session", json={}, headers={"Origin": ORIGIN})
        assert missing.status_code == 422


def test_missing_operator_credential_configuration_fails_closed() -> None:
    with client(token=None) as test_client:
        response = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "anything"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 503


def test_missing_session_secret_fails_closed_and_health_is_public() -> None:
    with client(secret=None) as test_client:
        response = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "test-operator-secret"},
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 503
        assert test_client.get("/api/v1/health").status_code == 200


def test_production_requires_authentication_secrets_and_explicit_origins() -> None:
    import pytest

    with pytest.raises(ValueError, match="SESSION_SIGNING_SECRET is required"):
        Settings(_env_file=None, app_env="production", api_access_token=SecretStr("operator"))
    shared_secret = "same-value" * 4
    with pytest.raises(ValueError, match="must be separate"):
        Settings(
            _env_file=None,
            app_env="test",
            api_access_token=SecretStr(shared_secret),
            session_signing_secret=SecretStr(shared_secret),
        )
    with pytest.raises(ValueError, match="CORS_ORIGINS"):
        Settings(
            _env_file=None,
            app_env="production",
            api_access_token=SecretStr("operator"),
            session_signing_secret=SecretStr("s" * 40),
        )
    with pytest.raises(ValueError, match="app_env"):
        Settings(_env_file=None, app_env="prod")


def test_production_session_cookie_is_secure() -> None:
    settings = Settings(
        _env_file=None,
        app_env="production",
        cors_origins=["https://dashboard.example"],
        api_access_token=SecretStr("operator"),
        session_signing_secret=SecretStr("s" * 40),
    )
    with TestClient(create_app(settings), base_url="https://testserver") as test_client:
        response = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "operator"},
            headers={"Origin": "https://dashboard.example"},
        )
        cookie = response.headers["set-cookie"].lower()
        assert response.status_code == 200
        assert "secure" in cookie
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/api/v1" in cookie
        test_client.cookies.set(
            auth_module.SESSION_COOKIE,
            test_client.cookies.get(auth_module.SESSION_COOKIE) + "tampered",
        )
        expired = test_client.get("/api/v1/auth/session")
        assert expired.status_code == 401
        deletion = expired.headers["set-cookie"].lower()
        assert "secure" in deletion
        assert "httponly" in deletion
        assert "samesite=strict" in deletion
        assert "path=/api/v1" in deletion


def test_approval_list_rejects_unauthenticated_operator() -> None:
    with client() as test_client:
        response = test_client.get(
            "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals"
        )
        assert response.status_code == 401


def test_approval_session_requires_origin_for_state_change(monkeypatch) -> None:
    class ApprovalRepository:
        def __init__(self, _session):
            pass

        def get_approval_request_by_id(self, _approval_id):
            return None

    monkeypatch.setattr(execution_routes, "ExecutionRepository", ApprovalRepository)
    with client() as test_client:
        test_client.post(
            "/api/v1/auth/session",
            json={"credential": "test-operator-secret"},
            headers={"Origin": ORIGIN},
        )
        response = test_client.post(
            "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals/00000000-0000-0000-0000-000000000001/approve"
        )
        assert response.status_code == 403
        allowed = test_client.post(
            "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals/00000000-0000-0000-0000-000000000001/approve",
            headers={"Origin": ORIGIN},
        )
        assert allowed.status_code == 404


def test_session_authentication_preserves_openai_router_protection(monkeypatch) -> None:
    class ApprovalRepository:
        def __init__(self, _session):
            pass

        def get_execution(self, _execution_id):
            return object()

        def get_approval_requests(self, **_kwargs):
            return []

    monkeypatch.setattr(execution_routes, "ExecutionRepository", ApprovalRepository)
    settings = Settings(
        _env_file=None,
        app_env="test",
        provider_mode="openai",
        openai_api_key=SecretStr("provider-key"),
        api_access_token=SecretStr("operator-bearer"),
        session_signing_secret=SecretStr("s" * 40),
        cors_origins=[ORIGIN],
    )
    with TestClient(create_app(settings)) as test_client:
        assert (
            test_client.get(
                "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals"
            ).status_code
            == 401
        )
        login = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "operator-bearer"},
            headers={"Origin": ORIGIN},
        )
        assert login.status_code == 200
        assert (
            test_client.get(
                "/api/v1/executions/00000000-0000-0000-0000-000000000000/approvals"
            ).status_code
            == 200
        )


def test_production_mock_mode_protects_workflow_and_execution_apis(monkeypatch) -> None:
    class ExecutionRepository:
        def __init__(self, _session):
            pass

        def list_executions(self, **_kwargs):
            return [], 0

    monkeypatch.setattr(workflow_routes, "list_workflows", lambda *_args, **_kwargs: ([], 0))
    monkeypatch.setattr(execution_routes, "ExecutionRepository", ExecutionRepository)
    settings = Settings(
        _env_file=None,
        app_env="production",
        provider_mode="mock",
        cors_origins=["https://dashboard.example"],
        api_access_token=SecretStr("production-operator-token"),
        session_signing_secret=SecretStr("p" * 40),
    )
    application = create_app(settings)
    with TestClient(application, base_url="https://testserver") as test_client:
        for path in ("/api/v1/workflows", "/api/v1/executions"):
            assert test_client.get(path).status_code == 401
            bearer_response = test_client.get(
                path,
                headers={"Authorization": "Bearer production-operator-token"},
            )
            assert bearer_response.status_code == 200

        login = test_client.post(
            "/api/v1/auth/session",
            json={"credential": "production-operator-token"},
            headers={"Origin": "https://dashboard.example"},
        )
        assert login.status_code == 200
        assert test_client.get("/api/v1/workflows").status_code == 200
        assert test_client.get("/api/v1/executions").status_code == 200
        missing_origin = test_client.post(
            "/api/v1/workflows",
            json={
                "name": "csrf-blocked",
                "tasks": [{"task_id": "analyze", "agent_type": "analyst"}],
            },
        )
        assert missing_origin.status_code == 403


def test_expired_session_entries_are_pruned(monkeypatch) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("test-operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    application = create_app(settings)
    with TestClient(application) as test_client:
        monkeypatch.setattr(auth_module.time, "time", lambda: 1_000)
        assert (
            test_client.post(
                "/api/v1/auth/session",
                json={"credential": "test-operator-secret"},
                headers={"Origin": ORIGIN},
            ).status_code
            == 200
        )
        first_token = test_client.cookies.get(auth_module.SESSION_COOKIE)
        assert first_token
        first_session_id = next(iter(application.state.active_sessions))

        monkeypatch.setattr(auth_module.time, "time", lambda: 3_000)
        test_client.cookies.set(auth_module.SESSION_COOKIE, first_token)
        assert test_client.get("/api/v1/auth/session").status_code == 401
        assert first_session_id not in application.state.active_sessions

        assert (
            test_client.post(
                "/api/v1/auth/session",
                json={"credential": "test-operator-secret"},
                headers={"Origin": ORIGIN},
            ).status_code
            == 200
        )
        second_session_id = next(iter(application.state.active_sessions))
        monkeypatch.setattr(auth_module.time, "time", lambda: 6_000)
        assert (
            test_client.post(
                "/api/v1/auth/session",
                json={"credential": "test-operator-secret"},
                headers={"Origin": ORIGIN},
            ).status_code
            == 200
        )
        assert second_session_id not in application.state.active_sessions
        assert len(application.state.active_sessions) == 1


def test_cors_credentials_are_scoped_to_configured_origin() -> None:
    with client() as test_client:
        response = test_client.options(
            "/api/v1/auth/session",
            headers={
                "Origin": ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
        assert response.headers["access-control-allow-origin"] == ORIGIN
        assert response.headers["access-control-allow-credentials"] == "true"
        denied = test_client.options(
            "/api/v1/auth/session",
            headers={
                "Origin": "https://attacker.example",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert "access-control-allow-origin" not in denied.headers
