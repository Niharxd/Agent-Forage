"""Dependencies for API services shared across route modules."""

from fastapi import Depends, Request

from agentforge.workflow.engine import WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrator


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
