"""Workflow execution lifecycle endpoints."""

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.auth import require_approval_operator
from agentforge.api.dependencies import (
    WorkflowAccess,
    get_workflow_engine,
    get_workflow_orchestrator,
    require_workflow_access,
)
from agentforge.api.responses import execution_response
from agentforge.api.schemas import (
    ExecutionApprovalResponse,
    ExecutionListResponse,
    ExecutionResponse,
    PageLimit,
)
from agentforge.api.services.executions import (
    ExecutionPersistenceError,
    ExecutionRepository,
)
from agentforge.api.services.workflows import get_workflow
from agentforge.database.dependencies import get_db_session
from agentforge.domain.workflows.models import WorkflowStatus
from agentforge.domain.workflows.validation import WorkflowValidationError
from agentforge.workflow.engine import (
    ExecutionNotFoundError,
    InvalidExecutionStateError,
    WorkflowEngine,
)
from agentforge.workflow.orchestrator import WorkflowOrchestrator

router = APIRouter(tags=["executions"])


@router.post(
    "/workflows/{workflow_id}/executions",
    response_model=ExecutionResponse,
    status_code=201,
)
def create_execution(
    workflow_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
    access: Annotated[WorkflowAccess, Depends(require_workflow_access)],
) -> ExecutionResponse:
    """Create a validated pending execution; no agent or tool runs until start."""
    workflow = get_workflow(session, workflow_id, workspace_id=access.workspace_id)
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
    return execution_response(snapshot)


@router.post("/executions/{execution_id}/start", response_model=ExecutionResponse)
def start_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_workflow_orchestrator)],
    access: Annotated[WorkflowAccess, Depends(require_workflow_access)],
) -> ExecutionResponse:
    """Synchronously run a pending execution through the existing workflow engine."""
    repository = ExecutionRepository(session)
    try:
        repository.get_execution(execution_id, workspace_id=access.workspace_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    orchestrator.engine._approval_repository = repository
    try:
        execution = orchestrator.start(execution_id, on_update=repository.synchronize_execution)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    except InvalidExecutionStateError as exc:
        raise HTTPException(
            status_code=409,
            detail="Execution cannot be started from its current state.",
        ) from exc
    return execution_response(execution)


@router.get(
    "/executions/{execution_id}/approvals",
    response_model=list[ExecutionApprovalResponse],
)
def list_execution_approvals(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    _operator: Annotated[None, Depends(require_approval_operator)],
) -> list[ExecutionApprovalResponse]:
    """List approval status and safe action descriptions for one execution."""
    repository = ExecutionRepository(session)
    try:
        repository.get_execution(execution_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    return [
        ExecutionApprovalResponse(
            approval_id=row.id,
            execution_id=row.execution_id,
            task_id=row.execution_step.task_id if row.execution_step else None,
            tool_id=row.tool_id,
            action_description=row.action_description,
            status=row.status,
            requested_at=row.requested_at,
            expires_at=row.expires_at,
            reviewed_at=row.reviewed_at,
        )
        for row in repository.get_approval_requests(execution_id=execution_id)
    ]


def _review_approval(
    execution_id: UUID,
    approval_id: UUID,
    approved: bool,
    session: Session,
    engine: WorkflowEngine,
) -> ExecutionResponse:
    repository = ExecutionRepository(session)
    approval = repository.get_approval_request_by_id(approval_id)
    if approval is None:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.execution_id != execution_id:
        raise HTTPException(status_code=404, detail="Approval not found.")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="Approval is no longer pending.")
    if approval.expires_at <= datetime.now(UTC):
        repository.expire_approval_request(approval_id)
        raise HTTPException(status_code=409, detail="Approval has expired.")
    engine._approval_repository = repository
    try:
        result = engine.approve(
            execution_id,
            approved=approved,
            task_id=approval.execution_step.task_id if approval.execution_step else None,
            on_update=repository.synchronize_execution,
        )
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=409, detail="Execution cannot resume.") from exc
    except InvalidExecutionStateError as exc:
        raise HTTPException(status_code=409, detail="Approval cannot be applied now.") from exc
    except ExecutionPersistenceError as exc:
        raise HTTPException(status_code=503, detail="Approval could not be persisted.") from exc
    return execution_response(result)


@router.post(
    "/executions/{execution_id}/approvals/{approval_id}/approve", response_model=ExecutionResponse
)
def approve_execution_approval(
    execution_id: UUID,
    approval_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
    _operator: Annotated[None, Depends(require_approval_operator)],
) -> ExecutionResponse:
    """Approve a persisted pending action and resume its execution."""
    return _review_approval(execution_id, approval_id, True, session, engine)


@router.post(
    "/executions/{execution_id}/approvals/{approval_id}/reject", response_model=ExecutionResponse
)
def reject_execution_approval(
    execution_id: UUID,
    approval_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
    _operator: Annotated[None, Depends(require_approval_operator)],
) -> ExecutionResponse:
    """Reject a persisted pending action and fail the waiting task safely."""
    return _review_approval(execution_id, approval_id, False, session, engine)


@router.get("/executions", response_model=ExecutionListResponse)
def get_executions(
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[WorkflowAccess, Depends(require_workflow_access)],
    limit: PageLimit = Query(default=50),
    offset: Annotated[int, Query(ge=0)] = 0,
    status: WorkflowStatus | None = None,
    search: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
) -> ExecutionListResponse:
    """List persisted executions with database-backed pagination and filters."""
    snapshots, total = ExecutionRepository(session).list_executions(
        limit=limit,
        offset=offset,
        status=status,
        search=search,
        workspace_id=access.workspace_id,
    )
    return ExecutionListResponse(
        items=[execution_response(item) for item in snapshots],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/executions/{execution_id}", response_model=ExecutionResponse)
def get_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    access: Annotated[WorkflowAccess, Depends(require_workflow_access)],
) -> ExecutionResponse:
    """Reconstruct persisted execution details and its safe plan projection."""
    try:
        snapshot, workflow_definition = ExecutionRepository(session).get_execution_details(
            execution_id,
            workspace_id=access.workspace_id,
        )
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    return execution_response(snapshot, workflow_definition)


@router.post("/executions/{execution_id}/cancel", response_model=ExecutionResponse)
def cancel_execution(
    execution_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_workflow_orchestrator)],
    access: Annotated[WorkflowAccess, Depends(require_workflow_access)],
) -> ExecutionResponse:
    """Cancel pending work or request cooperative cancellation of running work."""
    repository = ExecutionRepository(session)
    try:
        repository.get_execution(execution_id, workspace_id=access.workspace_id)
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    orchestrator.engine._approval_repository = repository
    try:
        snapshot = orchestrator.cancel(
            execution_id,
            on_update=repository.synchronize_execution,
        )
    except ExecutionNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Execution not found.") from exc
    except InvalidExecutionStateError as exc:
        raise HTTPException(
            status_code=409,
            detail="Execution cannot be cancelled from its current state.",
        ) from exc
    return execution_response(snapshot)
