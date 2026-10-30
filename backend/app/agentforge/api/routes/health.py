"""Liveness and readiness endpoints."""

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel

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
def get_readiness() -> HealthResponse:
    """Report API readiness; no external dependencies are initialized yet."""
    return HealthResponse(status="ready", checks={"application": "ready"})
