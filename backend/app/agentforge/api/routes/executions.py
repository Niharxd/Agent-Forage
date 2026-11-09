"""Workflow execution lifecycle endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.dependencies import get_workflow_engine, get_workflow_orchestrator
from agentforge.api.schemas import ExecutionListResponse, ExecutionResponse, PageLimit
from agentforge.api.services.executions import ExecutionRepository
from agentforge.api.services.workflows import get_workflow
from agentforge.database.dependencies import get_db_session
from agentforge.domain.workflows.models import WorkflowExecution, WorkflowExecutionSnapshot
from agentforge.domain.workflows.validation import WorkflowValidationError
from agentforge.workflow.engine import (
    ExecutionNotFoundError,
    InvalidExecutionStateError,
    WorkflowEngine,
)
from agentforge.workflow.orchestrator import WorkflowOrchestrator

router = APIRouter(tags=["executions"])


def _execution_response(
    execution: WorkflowExecution | WorkflowExecutionSnapshot,
) -> ExecutionResponse:
    snapshot = execution.snapshot() if isinstance(execution, WorkflowExecution) else execution
    return ExecutionResponse.model_validate(snapshot.model_dump(mode="python"))


@router.post(
    "/workflows/{workflow_id}/executions",
    response_model=ExecutionResponse,
    status_code=201,
)
def create_execution(
    workflow_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
) -> ExecutionResponse:
    """Create a validated pending execution; no agent or tool runs until start."""
    workflow = get_workflow(session, workflow_id)
    if workflow is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    try:
        repository = ExecutionRepository(session)
        snapshot = engine.create_execution(
            workflow.workflow_definition,
            on_update=lambda value: repository.create_execution(
                value,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                definition=workflow.workflow_definition,
            ),
        )
    except WorkflowValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "workflow_validation_error",
                    "message": "The workflow definition is invalid.",
                    "details": [
                        {"code": issue.code, "location": list(issue.location)}
                        for issue in exc.issues
                    ],
                }
            },
        ) from exc
    return _execution_response(snapshot)


@router.post("/executions/{execution_id}/start", response_model=ExecutionResponse)
def start_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_workflow_orchestrator)],
) -> ExecutionResponse:
    """Synchronously run a pending execution through the existing workflow engine."""
    repository = ExecutionRepository(session)
    try:
        execution = orchestrator.start(execution_id, on_update=repository.synchronize_execution)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    except InvalidExecutionStateError as exc:
        raise HTTPException(
            status_code=409,
            detail="Execution cannot be started from its current state.",
        ) from exc
    return _execution_response(execution)


@router.get("/executions", response_model=ExecutionListResponse)
def get_executions(
    session: Annotated[Session, Depends(get_db_session)],
    limit: PageLimit = Query(default=50),
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ExecutionListResponse:
    """List persisted executions with database-backed pagination."""
    snapshots, total = ExecutionRepository(session).list_executions(limit=limit, offset=offset)
    return ExecutionListResponse(
        items=[_execution_response(item) for item in snapshots],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
def get_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> ExecutionResponse:
    """Reconstruct an execution's state, events, and task-level results from PostgreSQL."""
    try:
        snapshot = ExecutionRepository(session).get_execution(execution_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    return _execution_response(snapshot)


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionResponse)
def cancel_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_workflow_orchestrator)],
) -> ExecutionResponse:
    """Cancel pending work or request cooperative cancellation of running work."""
    try:
        snapshot = orchestrator.cancel(
            execution_id,
            on_update=ExecutionRepository(session).synchronize_execution,
        )
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    except InvalidExecutionStateError as exc:
        raise HTTPException(
            status_code=409,
            detail="Execution cannot be cancelled from its current state.",
        ) from exc
    return _execution_response(snapshot)
