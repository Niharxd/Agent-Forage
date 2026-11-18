"""Browser session endpoints for the shared operator credential."""

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, SecretStr

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
