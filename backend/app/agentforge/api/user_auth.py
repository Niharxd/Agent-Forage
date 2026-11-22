"""Password and browser-session helpers for public users."""

import base64
import binascii
import hmac
import json
import secrets
import time
from threading import RLock
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request

USER_SESSION_COOKIE = "agentforge_user_session"
USER_SESSION_TTL_SECONDS = 1800
password_hasher = PasswordHasher()
_DUMMY_PASSWORD_HASH = password_hasher.hash(secrets.token_urlsafe(32))


def hash_password(password: str) -> str:
    """Hash a password with Argon2id using the library's current safe defaults."""
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str | None) -> bool:
    """Verify a password without treating malformed stored hashes as a match."""
    candidate_hash = password_hash or _DUMMY_PASSWORD_HASH
    try:
        return password_hasher.verify(candidate_hash, password)
    except (VerifyMismatchError, VerificationError, ValueError):
        return False


def _encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _secret(request: Request) -> bytes:
    configured = request.app.state.settings.session_signing_secret
    if configured is None or len(configured.get_secret_value()) < 32:
        raise HTTPException(status_code=503, detail="User authentication is unavailable.")
    return configured.get_secret_value().encode("utf-8")


def create_user_session(request: Request, user_id: UUID) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + USER_SESSION_TTL_SECONDS
    session_id = secrets.token_urlsafe(32)
    payload = _encode(
        json.dumps(
            {"sid": session_id, "uid": str(user_id), "exp": expires_at},
            separators=(",", ":"),
        ).encode()
    )
    signature = _encode(hmac.digest(_secret(request), payload.encode(), "sha256"))
    active_sessions: dict[str, int] = request.app.state.active_user_sessions
    lock: RLock = request.app.state.user_session_lock
    with lock:
        for active_id, active_expiration in list(active_sessions.items()):
            if active_expiration <= now:
                active_sessions.pop(active_id, None)
        active_sessions[session_id] = expires_at
    return f"{payload}.{signature}", expires_at


def get_user_session(request: Request) -> tuple[UUID, str] | None:
    token = request.cookies.get(USER_SESSION_COOKIE, "")
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = _encode(hmac.digest(_secret(request), payload.encode(), "sha256"))
        if not hmac.compare_digest(supplied_signature, expected):
            return None
        data: dict[str, Any] = json.loads(_decode(payload))
        session_id = data.get("sid")
        user_id = UUID(data["uid"])
        expires_at = data.get("exp")
        if not isinstance(session_id, str) or not isinstance(expires_at, int):
            return None
        active_sessions = request.app.state.active_user_sessions
        lock: RLock = request.app.state.user_session_lock
        with lock:
            if expires_at <= time.time():
                active_sessions.pop(session_id, None)
                return None
            if active_sessions.get(session_id) == expires_at:
                return user_id, session_id
            return None
    except (
        ValueError,
        TypeError,
        KeyError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        binascii.Error,
        HTTPException,
    ):
        return None


def revoke_user_session(request: Request) -> None:
    session = get_user_session(request)
    if session is not None:
        _, session_id = session
        with request.app.state.user_session_lock:
            request.app.state.active_user_sessions.pop(session_id, None)
