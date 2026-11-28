"""Security boundary checks for the platform administration API."""

from agentforge.config.settings import Settings
from agentforge.database.dependencies import get_db_session
from agentforge.main import create_app
from fastapi.testclient import TestClient
from pydantic import SecretStr


def test_platform_admin_rejects_public_and_bearer_operator_access() -> None:
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            api_access_token=SecretStr("operator-bearer-token"),
            session_signing_secret=SecretStr("x" * 48),
        )
    )
    app.dependency_overrides[get_db_session] = lambda: None

    with TestClient(app) as client:
        anonymous = client.get("/api/v1/platform-admin/overview")
        bearer = client.get(
            "/api/v1/platform-admin/overview",
            headers={"Authorization": "Bearer operator-bearer-token"},
        )

    assert anonymous.status_code == 401
    assert bearer.status_code == 401
