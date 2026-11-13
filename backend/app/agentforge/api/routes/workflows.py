"""Workflow definition validation and persistence endpoints."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from agentforge.api.dependencies import get_workflow_engine, get_workflow_orchestrator
from agentforge.api.responses import execution_response
from agentforge.api.schemas import (
    PageLimit,
    WorkflowCreateRequest,
    WorkflowListResponse,
    WorkflowPrepareRequest,
    WorkflowPrepareResponse,
    WorkflowResponse,
    WorkflowValidationIssueResponse,
    WorkflowValidationResponse,
)
from agentforge.api.services.workflows import (
    WorkflowVersionConflict,
    create_planned_workflow_execution,
    create_workflow,
    get_workflow,
    list_workflows,
    validate_request_schema,
)
from agentforge.database.dependencies import get_db_session
from agentforge.domain.workflows.models import WorkflowDefinition, WorkflowExecutionSnapshot
from agentforge.domain.workflows.validation import WorkflowValidationError
from agentforge.workflow.engine import WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrationError, WorkflowOrchestrator

router = APIRouter(prefix="/workflows", tags=["workflows"])

_SAFE_ISSUE_MESSAGES = {
    "circular_dependency": "Workflow dependencies must form a directed acyclic graph.",
    "duplicate_dependency": "A task lists the same dependency more than once.",
    "duplicate_task_id": "Task identifiers must be unique.",
    "maximum_task_limit": "The workflow exceeds the configured task limit.",
    "missing_dependency": "A task references an unknown dependency.",
    "self_dependency": "A task cannot depend on itself.",
    "task_input_limit": "A task input exceeds the configured size limit.",
    "unsafe_tool_request": "A tool request is invalid or not permitted for its agent.",
}


def _validation_issues(
    error: WorkflowValidationError,
) -> list[WorkflowValidationIssueResponse]:
    return [
        WorkflowValidationIssueResponse(
            code=issue.code,
            message=_SAFE_ISSUE_MESSAGES.get(
                issue.code,
                "The workflow definition does not satisfy a validation rule.",
            ),
            location=list(issue.location),
        )
        for issue in error.issues
    ]


@router.post("/validate", response_model=WorkflowValidationResponse)
def validate_workflow(
    body: WorkflowCreateRequest,
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
) -> WorkflowValidationResponse:
    """Validate a workflow and all declared tool permissions without storing it."""
    definition = validate_request_schema(body)
    try:
        validated = engine.validate_definition(definition)
    except WorkflowValidationError as exc:
        return WorkflowValidationResponse(valid=False, issues=_validation_issues(exc))
    return WorkflowValidationResponse(valid=True, workflow=validated)


@router.post(
    "/prepare",
    response_model=WorkflowPrepareResponse,
    status_code=201,
)
def prepare_workflow(
    body: WorkflowPrepareRequest,
    session: Annotated[Session, Depends(get_db_session)],
    orchestrator: Annotated[WorkflowOrchestrator, Depends(get_workflow_orchestrator)],
) -> WorkflowPrepareResponse:
    """Plan a task, persist its validated workflow, and leave it pending for review."""
    persisted_workflow: WorkflowResponse | None = None

    def persist_prepared(
        definition: WorkflowDefinition,
        snapshot: WorkflowExecutionSnapshot,
    ) -> None:
        nonlocal persisted_workflow
        persisted_workflow = create_planned_workflow_execution(
            session,
            definition,
            snapshot,
            original_task=body.task_description,
        )

    try:
        prepared = orchestrator.prepare(
            body.task_description,
            on_prepared=persist_prepared,
        )
    except (WorkflowOrchestrationError, WorkflowValidationError) as exc:
        raise HTTPException(
            status_code=502,
            detail="The Planner could not prepare a valid workflow.",
        ) from exc
    except WorkflowVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "workflow_version_conflict",
                    "message": "A workflow version could not be created.",
                    "details": [],
                }
            },
        ) from exc

    if persisted_workflow is None:
        raise RuntimeError("The prepared workflow was not persisted.")
    return WorkflowPrepareResponse(
        workflow=persisted_workflow,
        execution=execution_response(prepared.execution, prepared.workflow),
    )


@router.post("", response_model=WorkflowResponse, status_code=201)
def create_workflow_definition(
    body: WorkflowCreateRequest,
    session: Annotated[Session, Depends(get_db_session)],
    engine: Annotated[WorkflowEngine, Depends(get_workflow_engine)],
) -> WorkflowResponse:
    """Validate and persist a new version of a workflow definition."""
    definition = validate_request_schema(body)
    try:
        validated = engine.validate_definition(definition)
        return create_workflow(session, validated)
    except WorkflowValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "error": {
                    "code": "workflow_validation_error",
                    "message": "The workflow definition is invalid.",
                    "details": [issue.model_dump(mode="json") for issue in _validation_issues(exc)],
                }
            },
        ) from exc
    except WorkflowVersionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "workflow_version_conflict",
                    "message": "A workflow version could not be created.",
                    "details": [],
                }
            },
        ) from exc


@router.get("", response_model=WorkflowListResponse)
def get_workflows(
    session: Annotated[Session, Depends(get_db_session)],
    limit: PageLimit = Query(default=50),
    offset: Annotated[int, Query(ge=0)] = 0,
) -> WorkflowListResponse:
    """List persisted workflow definitions with pagination."""
    items, total = list_workflows(session, limit=limit, offset=offset)
    return WorkflowListResponse(items=items, total=total, limit=limit, offset=offset)


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow_definition(
    workflow_id: UUID,
    session: Annotated[Session, Depends(get_db_session)],
) -> WorkflowResponse:
    """Retrieve a workflow definition by its persistent identifier."""
    response = get_workflow(session, workflow_id)
    if response is None:
        raise HTTPException(status_code=404, detail="Workflow not found.")
    return response
