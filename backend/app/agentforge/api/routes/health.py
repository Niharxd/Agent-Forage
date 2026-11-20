"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok", "ready"]
    service: Literal["agentforge-api"] = "agentforge-api"
    version: Literal["v1"] = "v1"
    checks: dict[str, Literal["ok", "ready"]]


@router.get("/health", response_model=HealthResponse, tags=["health"])
def get_health() -> HealthResponse:
    """Report process liveness without depending on external services."""
    return HealthResponse(status="ok", checks={"liveness": "ok"})


@router.get("/ready", response_model=HealthResponse, tags=["health"])
def get_readiness(request: Request) -> HealthResponse:
    """Report readiness only when the application database responds."""
    try:
        session_factory = request.app.state.session_factory
        with session_factory() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Database readiness check failed",
        ) from exc
    return HealthResponse(status="ready", checks={"application": "ready"})
