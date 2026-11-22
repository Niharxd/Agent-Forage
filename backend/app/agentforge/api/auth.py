"""Optional shared-token authentication for provider-enabled API access."""

import base64
import binascii
import hmac
import json
import secrets
import time
from threading import RLock
from typing import Any

from fastapi import HTTPException, Request

SESSION_COOKIE = "agentforge_operator_session"
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 60


def secure_compare(left: str, right: str) -> bool:
    """Compare credentials as UTF-8 bytes, including non-ASCII input, in constant time."""
    return hmac.compare_digest(left.encode("utf-8"), right.encode("utf-8"))


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _session_secret(request: Request) -> bytes:
    secret = request.app.state.settings.session_signing_secret
    if secret is None or len(secret.get_secret_value()) < 32:
        raise HTTPException(status_code=503, detail="Operator sessions are unavailable.")
    return secret.get_secret_value().encode("utf-8")


def _session_store(request: Request) -> tuple[dict[str, int], RLock]:
    return request.app.state.active_sessions, request.app.state.session_lock


def validate_browser_origin(request: Request) -> None:
    """Reject browser state changes unless Origin exactly matches configured UI origin."""
    origin = request.headers.get("origin")
    if origin is None or origin not in request.app.state.settings.cors_origins:
        raise HTTPException(status_code=403, detail="Request origin is not allowed.")


def create_operator_session(request: Request) -> tuple[str, int]:
    """Create a signed, expiring session and register it for logout revocation."""
    now = int(time.time())
    expires_at = now + request.app.state.settings.operator_session_ttl_seconds
    session_id = secrets.token_urlsafe(32)
    payload = _encode(
        json.dumps({"sid": session_id, "exp": expires_at}, separators=(",", ":")).encode()
    )
    signature = _encode(hmac.digest(_session_secret(request), payload.encode(), "sha256"))
    active, lock = _session_store(request)
    with lock:
        for active_id, active_expiration in list(active.items()):
            if active_expiration <= now:
                active.pop(active_id, None)
        active[session_id] = expires_at
    return f"{payload}.{signature}", expires_at


def get_operator_session_id(request: Request) -> str | None:
    token = request.cookies.get(SESSION_COOKIE, "")
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = _encode(hmac.digest(_session_secret(request), payload.encode(), "sha256"))
        if not hmac.compare_digest(supplied_signature, expected):
            return None
        data: dict[str, Any] = json.loads(_decode(payload))
        session_id = data.get("sid")
        expires_at = data.get("exp")
        if not isinstance(session_id, str) or not isinstance(expires_at, int):
            return None
        active, lock = _session_store(request)
        with lock:
            if expires_at <= time.time():
                if active.get(session_id) == expires_at:
                    active.pop(session_id, None)
                return None
            if active.get(session_id) == expires_at:
                return session_id
            active.pop(session_id, None)
            return None
    except (
        ValueError,
        TypeError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        binascii.Error,
        HTTPException,
    ):
        return None


def revoke_operator_session(request: Request) -> None:
    session_id = get_operator_session_id(request)
    if session_id:
        active, lock = _session_store(request)
        with lock:
            active.pop(session_id, None)


def _login_client_key(request: Request, scope: str) -> str:
    client_key = request.client.host if request.client is not None else "unknown"
    return f"{scope}:{client_key}"


def check_login_rate_limit(request: Request, *, scope: str = "operator") -> None:
    """Reject repeated login attempts from one client for a short cooling-off period."""
    now = time.time()
    client_key = _login_client_key(request, scope)
    with request.app.state.session_lock:
        attempts, reset_at = request.app.state.login_attempts.get(client_key, (0, now))
        if reset_at <= now:
            request.app.state.login_attempts.pop(client_key, None)
            return
        if attempts >= LOGIN_FAILURE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Too many authentication attempts. Try again later.",
                headers={"Retry-After": str(max(1, int(reset_at - now)))},
            )


def record_login_failure(request: Request, *, scope: str = "operator") -> None:
    now = time.time()
    client_key = _login_client_key(request, scope)
    with request.app.state.session_lock:
        attempts, reset_at = request.app.state.login_attempts.get(client_key, (0, now))
        if reset_at <= now:
            attempts, reset_at = 0, now + LOGIN_FAILURE_WINDOW_SECONDS
        request.app.state.login_attempts[client_key] = (attempts + 1, reset_at)


def clear_login_failures(request: Request, *, scope: str = "operator") -> None:
    client_key = _login_client_key(request, scope)
    with request.app.state.session_lock:
        request.app.state.login_attempts.pop(client_key, None)


def require_browser_operator_session(request: Request) -> None:
    if get_operator_session_id(request) is None:
        raise HTTPException(status_code=401, detail="Operator authentication is required.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        validate_browser_origin(request)


def require_approval_operator(request: Request) -> None:
    """Accept legacy bearer auth or a CSRF-checked browser session on approval routes only."""
    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied = authorization.partition(" ")
    expected = request.app.state.settings.api_access_token
    if (
        separator
        and scheme.casefold() == "bearer"
        and supplied
        and expected is not None
        and secure_compare(supplied, expected.get_secret_value())
    ):
        return
    require_browser_operator_session(request)


def require_api_access_token(request: Request) -> None:
    """Require bearer or browser-session authentication on protected routers."""
    settings = request.app.state.settings
    if get_operator_session_id(request) is not None:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            validate_browser_origin(request)
        return
    expected_token = settings.api_access_token
    if expected_token is None:
        raise HTTPException(
            status_code=503,
            detail="Operator authentication is unavailable.",
        )

    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied_token = authorization.partition(" ")
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not supplied_token
        or not secure_compare(supplied_token, expected_token.get_secret_value())
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
