"""Password and browser-session helpers for public users."""

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError
from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agentforge.domain.models import User, UserSession

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


def _hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode("ascii")).hexdigest()


def _parse_user_session(request: Request) -> tuple[str, UUID, int] | None:
    token = request.cookies.get(USER_SESSION_COOKIE, "")
    try:
        payload, supplied_signature = token.split(".", 1)
        expected = _encode(hmac.digest(_secret(request), payload.encode(), "sha256"))
        if not hmac.compare_digest(supplied_signature, expected):
            return None
        data: dict[str, Any] = json.loads(_decode(payload).decode("utf-8"))
        session_id = data.get("sid")
        user_id = UUID(data["uid"])
        expires_at = data.get("exp")
        if not isinstance(session_id, str) or not isinstance(expires_at, int):
            return None
        return session_id, user_id, expires_at
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


def create_user_session(
    request: Request,
    db_session: Session,
    user_id: UUID,
) -> tuple[str, int]:
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
    db_session.add(
        UserSession(
            user_id=user_id,
            session_hash=_hash_session_id(session_id),
            created_at=datetime.now(UTC),
            expires_at=datetime.fromtimestamp(expires_at, UTC),
        )
    )
    return f"{payload}.{signature}", expires_at


def get_authenticated_user(request: Request, db_session: Session) -> User:
    parsed = _parse_user_session(request)
    if parsed is None:
        raise HTTPException(status_code=401, detail="User authentication is required.")
    session_id, token_user_id, token_expires_at = parsed
    if token_expires_at <= int(time.time()):
        raise HTTPException(status_code=401, detail="User authentication is required.")

    try:
        stored = db_session.scalar(
            select(UserSession).where(UserSession.session_hash == _hash_session_id(session_id))
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    if (
        not isinstance(stored, UserSession)
        or stored.user_id != token_user_id
        or stored.revoked_at is not None
        or stored.expires_at <= datetime.now(UTC)
    ):
        raise HTTPException(status_code=401, detail="User authentication is required.")

    try:
        user = db_session.get(User, stored.user_id)
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    if user is None or user.account_status in {"suspended", "deleted"}:
        raise HTTPException(status_code=401, detail="User authentication is required.")
    return user


def revoke_user_session(request: Request, db_session: Session) -> None:
    parsed = _parse_user_session(request)
    if parsed is None:
        return
    session_id, _token_user_id, _token_expires_at = parsed
    try:
        stored = db_session.scalar(
            select(UserSession).where(UserSession.session_hash == _hash_session_id(session_id))
        )
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=503,
            detail="User authentication is unavailable.",
        ) from exc
    if not isinstance(stored, UserSession):
        return
    if stored is not None and stored.revoked_at is None:
        stored.revoked_at = datetime.now(UTC)
        db_session.commit()
