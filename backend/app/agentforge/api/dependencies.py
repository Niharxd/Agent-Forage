"""Dependencies for API services shared across route modules."""

from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from agentforge.api.auth import require_api_access_token
from agentforge.api.user_auth import get_authenticated_user
from agentforge.database.dependencies import get_db_session
from agentforge.domain.models import User, Workspace, WorkspaceMembership
from agentforge.workflow.engine import WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrator

VALID_WORKSPACE_ROLES = {"owner", "admin", "member"}
APPROVAL_WORKSPACE_ROLES = {"owner", "admin"}


@dataclass(frozen=True)
class WorkflowAccess:
    workspace_id: UUID
    user_id: UUID | None
    role: str
    operator: bool = False


def require_authenticated_user(
    request: Request,
    db_session: Session = Depends(get_db_session),
) -> User:
    """Return the persistent authenticated public user or fail closed."""
    return get_authenticated_user(request, db_session)


def get_personal_workspace_role(session: Session, user: User) -> str | None:
    """Resolve the authenticated user's active personal-workspace membership role."""
    try:
        role = session.scalar(
            select(WorkspaceMembership.role)
            .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                WorkspaceMembership.user_id == user.id,
                Workspace.owner_id == user.id,
                Workspace.slug.like("personal-%"),
                Workspace.status == "active",
            )
            .order_by(WorkspaceMembership.joined_at.asc())
        )
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=503, detail="Workspace access is unavailable.") from exc
    return role if role in VALID_WORKSPACE_ROLES else None


def require_workflow_access(
    request: Request,
    db_session: Session = Depends(get_db_session),
) -> WorkflowAccess:
    """Resolve public workspace access or an explicit operator access path."""
    try:
        require_api_access_token(request)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
    except (AttributeError, KeyError):
        pass
    else:
        try:
            legacy_workspace = db_session.scalar(
                select(Workspace).where(Workspace.slug == "legacy-operator")
            )
        except (SQLAlchemyError, AttributeError):
            legacy_workspace = None
        if legacy_workspace is not None:
            if legacy_workspace.status != "active":
                raise HTTPException(status_code=503, detail="Operator workspace is unavailable.")
            return WorkflowAccess(
                workspace_id=legacy_workspace.id,
                user_id=legacy_workspace.owner_id,
                role="owner",
                operator=True,
            )
        settings = request.app.state.settings
        if (
            settings.app_env == "test"
            or settings.provider_mode == "mock"
            or settings.provider_mode == "openai"
        ):
            return WorkflowAccess(
                workspace_id=UUID(int=0),
                user_id=None,
                role="owner",
                operator=True,
            )
        raise HTTPException(status_code=503, detail="Operator workspace is unavailable.")

    try:
        user = get_authenticated_user(request, db_session)
    except HTTPException as exc:
        if exc.status_code != 401:
            raise
        raise HTTPException(status_code=401, detail="Authentication is required.") from exc

    try:
        membership = db_session.scalar(
            select(WorkspaceMembership)
            .join(Workspace, WorkspaceMembership.workspace_id == Workspace.id)
            .where(
                WorkspaceMembership.user_id == user.id,
                Workspace.owner_id == user.id,
                Workspace.slug.like("personal-%"),
            )
            .order_by(WorkspaceMembership.joined_at.asc())
        )
    except SQLAlchemyError as db_exc:
        raise HTTPException(status_code=503, detail="Workspace access is unavailable.") from db_exc

    if membership is None:
        raise HTTPException(status_code=403, detail="Workspace access is required.")
    if membership.role not in VALID_WORKSPACE_ROLES:
        raise HTTPException(status_code=403, detail="Workspace role is not valid.")
    if membership.workspace.status != "active":
        raise HTTPException(status_code=403, detail="Workspace access is inactive.")
    if user.account_status in {"suspended", "deleted"}:
        raise HTTPException(status_code=401, detail="User authentication is required.")

    return WorkflowAccess(
        workspace_id=membership.workspace_id,
        user_id=user.id,
        role=membership.role,
    )


def require_approval_access(
    access: WorkflowAccess = Depends(require_workflow_access),
) -> WorkflowAccess:
    """Require an operator or a privileged workspace role to decide approvals."""
    if not access.operator and access.role not in APPROVAL_WORKSPACE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Owner or admin access is required to decide approvals.",
        )
    return access


def require_workflow_management_access(
    access: WorkflowAccess = Depends(require_workflow_access),
) -> WorkflowAccess:
    """Require operator, owner, or admin access for workflow metadata and lifecycle changes."""
    if not access.operator and access.role not in APPROVAL_WORKSPACE_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Owner or admin access is required to manage workflows.",
        )
    return access


def get_workflow_engine(request: Request) -> WorkflowEngine:
    """Return the process-local workflow engine initialized by the application."""
    engine = getattr(request.app.state, "workflow_engine", None)
    if engine is None:
        raise RuntimeError("The workflow engine has not been initialized")
    return engine


def get_workflow_orchestrator(
    engine: WorkflowEngine = Depends(get_workflow_engine),
) -> WorkflowOrchestrator:
    """Bind the existing orchestration API to this request's workflow engine."""
    return WorkflowOrchestrator(engine=engine)
