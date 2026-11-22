"""Dependencies for API services shared across route modules."""

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from agentforge.api.user_auth import get_authenticated_user
from agentforge.database.dependencies import get_db_session
from agentforge.domain.models import User
from agentforge.workflow.engine import WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrator


def require_authenticated_user(
    request: Request,
    db_session: Session = Depends(get_db_session),
) -> User:
    """Return the persistent authenticated public user or fail closed."""
    return get_authenticated_user(request, db_session)


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
