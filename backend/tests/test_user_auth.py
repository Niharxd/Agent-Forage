from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentforge.api.user_auth import (
    USER_SESSION_COOKIE,
    create_user_session,
    get_authenticated_user,
    hash_password,
    revoke_user_session,
    verify_password,
)
from agentforge.config.settings import Settings
from agentforge.database.dependencies import get_db_session
from agentforge.domain.models import User, UserSession
from agentforge.main import create_app
from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

ORIGIN = "http://localhost:5173"
PASSWORD = "StrongPassword123"


class FakeSession:
    def __init__(
        self,
        user: User | None = None,
        *,
        fail_commit: bool = False,
        fail_database: bool = False,
    ):
        self.user = user
        self.fail_commit = fail_commit
        self.fail_database = fail_database
        self.records: list[object] = []
        self.workspace_role = "owner"

    def scalar(self, _statement: object) -> object | None:
        if self.fail_database:
            raise SQLAlchemyError("database unavailable")
        if "workspace_memberships.role" in str(_statement):
            return self.workspace_role
        sessions = [record for record in self.records if isinstance(record, UserSession)]
        if sessions:
            return sessions[-1]
        return self.user

    def get(self, _model: object, _identity: object) -> User | None:
        if self.fail_database:
            raise SQLAlchemyError("database unavailable")
        return self.user

    def add(self, record: object) -> None:
        self.records.append(record)
        if isinstance(record, UserSession) and record.id is None:
            record.id = uuid4()

    def add_all(self, records: list[object]) -> None:
        self.records.extend(records)
        for record in records:
            if getattr(record, "id", None) is None:
                record.id = uuid4()

    def commit(self) -> None:
        if self.fail_commit or self.fail_database:
            raise IntegrityError("insert", {}, RuntimeError("duplicate"))
        for record in self.records:
            if isinstance(record, User):
                self.user = record

    def rollback(self) -> None:
        self.records.clear()


def make_client(session: FakeSession) -> TestClient:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    application = create_app(settings)
    application.dependency_overrides[get_db_session] = lambda: session
    client = TestClient(application)
    client.headers.update({"Origin": ORIGIN})
    return client


def test_registration_normalizes_email_and_creates_owner_workspace() -> None:
    session = FakeSession()
    with make_client(session) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "  User@Example.COM ", "password": PASSWORD},
        )

    assert response.status_code == 201
    assert response.json()["user"]["email"] == "user@example.com"
    assert response.json()["user"]["account_status"] == "pending"
    assert "password_hash" not in response.text
    user, workspace, membership = session.records
    assert isinstance(user, User)
    assert user.password_hash != PASSWORD
    assert verify_password(PASSWORD, user.password_hash)
    assert workspace.owner is user
    assert membership.user is user
    assert membership.workspace is workspace
    assert membership.role == "owner"


def test_registration_rejects_invalid_origin() -> None:
    with make_client(FakeSession()) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": PASSWORD},
            headers={"Origin": "https://attacker.example"},
        )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "payload",
    [
        {"email": "not-an-email", "password": PASSWORD},
        {"email": "user@example.com", "password": "weakpassword"},
    ],
)
def test_registration_rejects_invalid_input(payload: dict[str, str]) -> None:
    with make_client(FakeSession()) as client:
        response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 422


def test_registration_duplicate_rolls_back() -> None:
    session = FakeSession(fail_commit=True)
    with make_client(session) as client:
        response = client.post(
            "/api/v1/auth/register",
            json={"email": "user@example.com", "password": PASSWORD},
        )
    assert response.status_code == 409
    assert session.records == []


def test_password_hash_is_argon2id() -> None:
    password_hash = hash_password(PASSWORD)
    assert password_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, password_hash)
    assert not verify_password("wrong", password_hash)


@pytest.mark.parametrize("account_status", ["suspended", "deleted"])
def test_login_rejects_non_active_accounts(account_status: str) -> None:
    user = User(
        id=uuid4(),
        email="user@example.com",
        password_hash=hash_password(PASSWORD),
        account_status=account_status,
    )
    with make_client(FakeSession(user)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "USER@EXAMPLE.COM", "password": PASSWORD},
        )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication is required."


def test_login_sets_separate_user_cookie_and_updates_last_login() -> None:
    user = User(
        id=uuid4(),
        email="user@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    session = FakeSession(user)
    with make_client(session) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": " USER@EXAMPLE.COM ", "password": PASSWORD},
        )
        assert response.status_code == 200
        assert USER_SESSION_COOKIE in response.headers["set-cookie"]
        cookie = response.headers["set-cookie"].lower()
        assert "httponly" in cookie
        assert "samesite=strict" in cookie
        assert "path=/api/v1" in cookie
        assert response.json()["user"]["email"] == "user@example.com"
        assert "password_hash" not in response.text
        status = client.get("/api/v1/auth/user-session")
        assert status.status_code == 200
        assert status.json()["email"] == "user@example.com"
        assert client.delete("/api/v1/auth/logout").status_code == 204
    assert isinstance(user.last_login_at, datetime)
    assert user.last_login_at.tzinfo == UTC
    assert any(isinstance(record, UserSession) for record in session.records)


def test_login_commit_failure_does_not_issue_user_cookie() -> None:
    user = User(
        id=uuid4(),
        email="commit-failure@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    session = FakeSession(user, fail_database=True)
    with make_client(session) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "commit-failure@example.com", "password": PASSWORD},
        )
        assert response.status_code == 503
        assert USER_SESSION_COOKIE not in response.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/user-session").status_code == 401


def test_login_commit_exception_does_not_issue_user_cookie() -> None:
    user = User(
        id=uuid4(),
        email="commit-error@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    session = FakeSession(user, fail_commit=True)
    with make_client(session) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "commit-error@example.com", "password": PASSWORD},
        )
        assert response.status_code == 503
        assert USER_SESSION_COOKIE not in response.headers.get("set-cookie", "")


def test_login_rate_limit_is_scoped_to_public_users() -> None:
    with make_client(FakeSession()) as client:
        for _ in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "wrong-password"},
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong-password"},
        )
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert blocked.headers["retry-after"]


def test_user_rate_limit_does_not_block_operator_login() -> None:
    with make_client(FakeSession()) as client:
        for _ in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"email": "user@example.com", "password": "wrong-password"},
            )
            assert response.status_code == 401
        operator_response = client.post(
            "/api/v1/auth/session",
            json={"credential": "operator-secret"},
        )
    assert operator_response.status_code == 200


def test_login_rejects_invalid_origin_without_consuming_rate_limit() -> None:
    with make_client(FakeSession()) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": "wrong-password"},
            headers={"Origin": "https://attacker.example"},
        )
    assert response.status_code == 403


def test_logout_rejects_invalid_origin() -> None:
    with make_client(FakeSession()) as client:
        response = client.delete(
            "/api/v1/auth/logout",
            headers={"Origin": "https://attacker.example"},
        )
    assert response.status_code == 403


def test_pending_accounts_can_log_in() -> None:
    user = User(
        id=uuid4(),
        email="user@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="pending",
    )
    with make_client(FakeSession(user)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "user@example.com", "password": PASSWORD},
        )
    assert response.status_code == 200


@pytest.mark.parametrize("email", ["unknown@example.com", "user@example.com"])
def test_login_invalid_credentials_are_indistinguishable(email: str) -> None:
    user = (
        None
        if email.startswith("unknown")
        else User(
            id=uuid4(),
            email=email,
            password_hash=hash_password(PASSWORD),
            account_status="active",
        )
    )
    with make_client(FakeSession(user)) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "wrong-password"},
        )
    assert response.status_code == 401
    assert response.json()["error"]["message"] == "Authentication is required."


def make_user_request(application, token: str) -> Request:
    return Request(
        {
            "type": "http",
            "app": application,
            "headers": [(b"cookie", f"{USER_SESSION_COOKIE}={token}".encode("ascii"))],
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 123),
            "scheme": "http",
        }
    )


def test_persistent_session_lookup_and_restart_reuse() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    user = User(
        id=uuid4(),
        email="restart@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    db = FakeSession(user)
    app_before_restart = create_app(settings)
    token, _expires_at = create_user_session(
        make_user_request(app_before_restart, ""),
        db,
        user.id,
    )

    app_after_restart = create_app(settings)
    request = make_user_request(app_after_restart, token)
    assert get_authenticated_user(request, db) is user


@pytest.mark.parametrize("status", ["suspended", "deleted"])
def test_persistent_session_rejects_ineligible_users(status: str) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    user = User(
        id=uuid4(),
        email=f"{status}@example.com",
        password_hash=hash_password(PASSWORD),
        account_status=status,
    )
    db = FakeSession(user)
    app = create_app(settings)
    token, _expires_at = create_user_session(make_user_request(app, ""), db, user.id)
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, token), db)
    assert exc.value.status_code == 401


def test_expired_revoked_unknown_and_malformed_sessions_are_rejected() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    user = User(
        id=uuid4(),
        email="sessions@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    db = FakeSession(user)
    app = create_app(settings)

    token, _expires_at = create_user_session(make_user_request(app, ""), db, user.id)
    stored = next(record for record in db.records if isinstance(record, UserSession))
    stored.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, token), db)
    assert exc.value.status_code == 401

    stored.expires_at = datetime.now(UTC) + timedelta(minutes=30)
    stored.revoked_at = datetime.now(UTC)
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, token), db)
    assert exc.value.status_code == 401

    db.records.clear()
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, token), db)
    assert exc.value.status_code == 401

    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, "malformed"), db)
    assert exc.value.status_code == 401


def test_logout_revokes_persistent_session() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    user = User(
        id=uuid4(),
        email="logout@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    db = FakeSession(user)
    app = create_app(settings)
    token, _expires_at = create_user_session(make_user_request(app, ""), db, user.id)
    request = make_user_request(app, token)
    revoke_user_session(request, db)
    stored = next(record for record in db.records if isinstance(record, UserSession))
    assert stored.revoked_at is not None
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(request, db)
    assert exc.value.status_code == 401


def test_logout_database_failure_returns_unavailable() -> None:
    user = User(
        id=uuid4(),
        email="logout-failure@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    db = FakeSession(user)
    app = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            cors_origins=[ORIGIN],
            api_access_token=SecretStr("operator-secret"),
            session_signing_secret=SecretStr("s" * 40),
        )
    )
    token, _expires_at = create_user_session(make_user_request(app, ""), db, user.id)

    with make_client(db) as client:
        client.cookies.set(USER_SESSION_COOKIE, token)
        db.fail_database = True
        response = client.delete(
            "/api/v1/auth/logout",
            headers={"Origin": ORIGIN},
        )
        assert response.status_code == 503


def test_database_failure_fails_closed() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        cors_origins=[ORIGIN],
        api_access_token=SecretStr("operator-secret"),
        session_signing_secret=SecretStr("s" * 40),
    )
    user = User(
        id=uuid4(),
        email="database@example.com",
        password_hash=hash_password(PASSWORD),
        account_status="active",
    )
    db = FakeSession(user, fail_database=True)
    app = create_app(settings)
    token, _expires_at = create_user_session(make_user_request(app, ""), db, user.id)
    with pytest.raises(HTTPException) as exc:
        get_authenticated_user(make_user_request(app, token), db)
    assert exc.value.status_code == 503
