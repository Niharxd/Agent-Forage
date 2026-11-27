"""Authentication endpoints for operators and public users."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from agentforge.api.auth import (
    SESSION_COOKIE,
    check_login_rate_limit,
    clear_login_failures,
    create_operator_session,
    get_operator_session_id,
    record_login_failure,
    revoke_operator_session,
    secure_compare,
    validate_browser_origin,
)
from agentforge.api.dependencies import get_personal_workspace_role, require_authenticated_user
from agentforge.api.schemas import (
    LoginRequest,
    LoginResponse,
    RegistrationRequest,
    RegistrationResponse,
    UserResponse,
    UserSessionResponse,
)
from agentforge.api.user_auth import (
    USER_SESSION_COOKIE,
    create_user_session,
    hash_password,
    revoke_user_session,
    verify_password,
)
from agentforge.database.dependencies import get_db_session
from agentforge.domain.models import User, Workspace, WorkspaceMembership

router = APIRouter(prefix="/auth", tags=["authentication"])


class SessionLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential: SecretStr


@router.post("/session")
def login(body: SessionLogin, request: Request, response: Response) -> dict[str, object]:
    validate_browser_origin(request)
    check_login_rate_limit(request)
    settings = request.app.state.settings
    expected = settings.api_access_token
    if expected is None or not expected.get_secret_value().strip():
        raise HTTPException(status_code=503, detail="Operator authentication is unavailable.")
    if not secure_compare(body.credential.get_secret_value(), expected.get_secret_value()):
        record_login_failure(request)
        raise HTTPException(status_code=401, detail="The operator credential is invalid.")
    clear_login_failures(request)
    token, expires_at = create_operator_session(request)
    response.set_cookie(
        SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.app_env.casefold() == "production",
        samesite="strict",
        path="/api/v1",
        max_age=settings.operator_session_ttl_seconds,
    )
    return {"authenticated": True, "expires_at": expires_at}


@router.get("/session", response_model=None)
def session_status(request: Request) -> dict[str, object] | Response:
    session_id = get_operator_session_id(request)
    if session_id is None:
        unauthorized = JSONResponse(
            status_code=401,
            content={"detail": "Operator authentication is required."},
        )
        unauthorized.delete_cookie(
            SESSION_COOKIE,
            path="/api/v1",
            httponly=True,
            secure=request.app.state.settings.app_env.casefold() == "production",
            samesite="strict",
        )
        return unauthorized
    return {"authenticated": True}


@router.delete("/session", status_code=204)
def logout(request: Request, response: Response) -> Response:
    validate_browser_origin(request)
    revoke_operator_session(request)
    response.delete_cookie(
        SESSION_COOKIE,
        path="/api/v1",
        httponly=True,
        secure=request.app.state.settings.app_env.casefold() == "production",
        samesite="strict",
    )
    response.status_code = 204
    return response


@router.post("/register", response_model=RegistrationResponse, status_code=201)
def register(
    body: RegistrationRequest,
    request: Request,
    session: Session = Depends(get_db_session),
) -> RegistrationResponse:
    """Create a pending user, personal workspace, and owner membership atomically."""
    validate_browser_origin(request)
    user = User(
        email=body.email,
        password_hash=hash_password(body.password),
        account_status="pending",
    )
    workspace = Workspace(
        name="Personal Workspace",
        slug=f"personal-{uuid4().hex}",
        owner=user,
        status="active",
    )
    membership = WorkspaceMembership(workspace=workspace, user=user, role="owner")
    session.add_all([user, workspace, membership])
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="An account with that email already exists.",
        ) from exc
    return RegistrationResponse(user=UserResponse.model_validate(user), workspace_id=workspace.id)


@router.post("/login", response_model=LoginResponse)
def user_login(
    body: LoginRequest,
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> LoginResponse:
    """Authenticate a user without exposing account existence in failures."""
    validate_browser_origin(request)
    check_login_rate_limit(request, scope="user")
    try:
        user = session.scalar(select(User).where(User.email == body.email))
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    password_valid = verify_password(body.password, user.password_hash if user else None)
    if user is None or user.account_status in {"suspended", "deleted"} or not password_valid:
        record_login_failure(request, scope="user")
        raise HTTPException(status_code=401, detail="Invalid email or password.")

    clear_login_failures(request, scope="user")
    user.last_login_at = datetime.now(UTC)
    try:
        token, expires_at = create_user_session(request, session, user.id)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    settings = request.app.state.settings
    response.set_cookie(
        USER_SESSION_COOKIE,
        token,
        httponly=True,
        secure=settings.app_env.casefold() == "production",
        samesite="strict",
        path="/api/v1",
        max_age=1800,
    )
    return LoginResponse(user=UserResponse.model_validate(user), expires_at=expires_at)


@router.delete("/logout", status_code=204)
def user_logout(
    request: Request,
    response: Response,
    session: Session = Depends(get_db_session),
) -> Response:
    """Revoke the current public-user browser session."""
    validate_browser_origin(request)
    try:
        revoke_user_session(request, session)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    response.delete_cookie(
        USER_SESSION_COOKIE,
        path="/api/v1",
        httponly=True,
        secure=request.app.state.settings.app_env.casefold() == "production",
        samesite="strict",
    )
    response.status_code = 204
    return response


@router.get("/user-session", response_model=UserSessionResponse)
def user_session_status(
    user: User = Depends(require_authenticated_user),
    session: Session = Depends(get_db_session),
) -> UserSessionResponse:
    """Return the identity established by the persistent public-user cookie."""
    return UserSessionResponse(
        **UserResponse.model_validate(user).model_dump(),
        workspace_role=get_personal_workspace_role(session, user),
    )
