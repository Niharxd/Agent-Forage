"""Platform administration, restricted to the existing authenticated operator boundary."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agentforge.api.auth import require_browser_operator_session
from agentforge.database.dependencies import get_db_session
from agentforge.domain.models import (
    PlatformAdminAudit,
    User,
    UserSession,
    Workflow,
    WorkflowExecution,
    Workspace,
)

router = APIRouter(prefix="/platform-admin", tags=["platform administration"])


def _user_payload(user: User) -> dict:
    return {
        "id": str(user.id),
        "email": user.email,
        "account_status": user.account_status,
        "created_at": user.created_at,
        "last_login_at": user.last_login_at,
        "email_verified_at": user.email_verified_at,
        "workspaces": [
            {
                "id": str(membership.workspace.id),
                "name": membership.workspace.name,
                "slug": membership.workspace.slug,
                "role": membership.role,
            }
            for membership in user.workspace_memberships
        ],
    }


class StatusChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str


def _operator(request: Request) -> None:
    """Treat a validated operator browser session as platform administration authority."""
    require_browser_operator_session(request)


@router.get("/overview")
def overview(_: None = Depends(_operator), db: Session = Depends(get_db_session)) -> dict:
    statuses = dict(
        db.execute(select(User.account_status, func.count()).group_by(User.account_status)).all()
    )
    recent = db.scalars(
        select(PlatformAdminAudit).order_by(PlatformAdminAudit.occurred_at.desc()).limit(8)
    ).all()
    return {
        "users": {
            "total": sum(statuses.values()),
            "active": statuses.get("active", 0),
            "pending": statuses.get("pending", 0),
            "suspended": statuses.get("suspended", 0),
        },
        "workspaces": db.scalar(select(func.count()).select_from(Workspace)) or 0,
        "workflows": db.scalar(select(func.count()).select_from(Workflow)) or 0,
        "executions": db.scalar(select(func.count()).select_from(WorkflowExecution)) or 0,
        "recent_activity": [
            {
                "action": record.action,
                "target_user_id": str(record.target_user_id),
                "occurred_at": record.occurred_at,
            }
            for record in recent
        ],
    }


@router.get("/users")
def users(
    q: str = Query(default="", max_length=320),
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(_operator),
    db: Session = Depends(get_db_session),
) -> dict:
    query = select(User)
    if q.strip():
        query = query.where(User.email.ilike(f"%{q.strip()}%"))
    if status:
        if status not in {"active", "pending", "suspended", "deleted"}:
            raise HTTPException(status_code=422, detail="Invalid account status filter.")
        query = query.where(User.account_status == status)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(User.created_at.desc()).offset(offset).limit(limit)).all()
    return {
        "items": [_user_payload(user) for user in rows],
        "total": total,
    }


@router.get("/users/{user_id}")
def user_detail(
    user_id: UUID,
    _: None = Depends(_operator),
    db: Session = Depends(get_db_session),
) -> dict:
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return _user_payload(user)


@router.patch("/users/{user_id}/status")
def change_user_status(
    user_id: UUID,
    body: StatusChange,
    request: Request,
    _: None = Depends(_operator),
    db: Session = Depends(get_db_session),
) -> dict:
    if body.status not in {"active", "pending", "suspended"}:
        raise HTTPException(status_code=422, detail="Status transition is not allowed.")
    user = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")
    if user.account_status == "deleted":
        raise HTTPException(status_code=409, detail="Deleted accounts cannot be changed.")
    allowed_transitions = {
        "pending": {"active", "suspended"},
        "active": {"suspended"},
        "suspended": {"active"},
    }
    if body.status not in allowed_transitions.get(user.account_status, set()):
        raise HTTPException(status_code=409, detail="Status transition is not allowed.")
    if user.account_status == body.status:
        return {"id": str(user.id), "account_status": user.account_status}
    previous = user.account_status
    user.account_status = body.status
    if body.status == "suspended":
        db.execute(
            update(UserSession)
            .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
    db.add(
        PlatformAdminAudit(
            action=f"user_{body.status}",
            target_user_id=user.id,
            details={"from": previous, "to": body.status},
        )
    )
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail="Account update unavailable.") from exc
    return {"id": str(user.id), "account_status": user.account_status}


@router.get("/workspaces")
def workspaces(
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    _: None = Depends(_operator),
    db: Session = Depends(get_db_session),
) -> dict:
    query = select(Workspace)
    if q.strip():
        needle = f"%{q.strip()}%"
        query = query.where(or_(Workspace.name.ilike(needle), Workspace.slug.ilike(needle)))
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = db.scalars(query.order_by(Workspace.created_at.desc()).offset(offset).limit(limit)).all()
    items = []
    for workspace in rows:
        items.append(
            {
                "id": str(workspace.id),
                "name": workspace.name,
                "slug": workspace.slug,
                "status": workspace.status,
                "created_at": workspace.created_at,
                "owner": {"id": str(workspace.owner.id), "email": workspace.owner.email},
                "members": [
                    {"id": str(m.user.id), "email": m.user.email, "role": m.role}
                    for m in workspace.memberships
                ],
                "workflow_count": db.scalar(
                    select(func.count())
                    .select_from(Workflow)
                    .where(Workflow.workspace_id == workspace.id)
                )
                or 0,
                "execution_count": db.scalar(
                    select(func.count())
                    .select_from(WorkflowExecution)
                    .where(WorkflowExecution.workspace_id == workspace.id)
                )
                or 0,
            }
        )
    return {"items": items, "total": total}
