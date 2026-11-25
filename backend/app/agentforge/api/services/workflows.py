"""Persistence operations for versioned workflow definitions."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentforge.api.schemas import WorkflowCreateRequest, WorkflowResponse
from agentforge.api.services.executions import ExecutionRepository
from agentforge.domain.models import Workflow, Workspace
from agentforge.domain.workflows.models import WorkflowDefinition, WorkflowExecutionSnapshot


class WorkflowVersionConflict(Exception):
    """Raised when a concurrently-created workflow version violates uniqueness."""


def create_workflow(
    session: Session,
    definition: WorkflowDefinition,
    *,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> WorkflowResponse:
    """Persist one validated definition as the next version of its name."""
    if workspace_id is None or user_id is None:
        legacy = session.scalar(select(Workspace).where(Workspace.slug == "legacy-operator"))
        if legacy is None:
            raise RuntimeError("The legacy operator workspace is not initialized.")
        workspace_id = workspace_id or legacy.id
        user_id = user_id or legacy.owner_id
    record = _new_workflow_record(
        session,
        definition,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    session.add(record)
    try:
        session.commit()
        session.refresh(record)
    except IntegrityError as exc:
        session.rollback()
        raise WorkflowVersionConflict from exc
    return workflow_response(record)


def create_planned_workflow_execution(
    session: Session,
    definition: WorkflowDefinition,
    snapshot: WorkflowExecutionSnapshot,
    *,
    original_task: str,
    workspace_id: UUID | None = None,
    user_id: UUID | None = None,
) -> WorkflowResponse:
    """Persist a planner-created workflow and its initial execution atomically."""
    if workspace_id is None or user_id is None:
        legacy = session.scalar(select(Workspace).where(Workspace.slug == "legacy-operator"))
        if legacy is None:
            raise RuntimeError("The legacy operator workspace is not initialized.")
        workspace_id = workspace_id or legacy.id
        user_id = user_id or legacy.owner_id
    record = _new_workflow_record(
        session,
        definition,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    session.add(record)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        raise WorkflowVersionConflict from exc

    try:
        saved_workflow = workflow_response(record)
    except Exception:
        session.rollback()
        raise

    ExecutionRepository(session).create_execution(
        snapshot,
        workflow_id=record.id,
        workflow_version=record.version,
        definition=definition,
        original_task=original_task,
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        actor_user_id=user_id,
    )
    return saved_workflow


def _new_workflow_record(
    session: Session,
    definition: WorkflowDefinition,
    *,
    workspace_id: UUID,
    user_id: UUID,
) -> Workflow:
    latest_version = session.scalar(
        select(func.max(Workflow.version)).where(
            Workflow.workspace_id == workspace_id,
            Workflow.name == definition.name,
        )
    )
    return Workflow(
        name=definition.name,
        description=definition.description,
        version=(latest_version or 0) + 1,
        workflow_definition=definition.model_dump(mode="json"),
        workspace_id=workspace_id,
        created_by_user_id=user_id,
        updated_by_user_id=user_id,
    )


def get_workflow(
    session: Session,
    workflow_id: UUID,
    *,
    workspace_id: UUID,
) -> WorkflowResponse | None:
    """Return a workflow response without exposing the SQLAlchemy object."""
    record = session.scalar(
        select(Workflow).where(
            Workflow.id == workflow_id,
            Workflow.workspace_id == workspace_id,
        )
    )
    return workflow_response(record) if record is not None else None


def list_workflows(
    session: Session,
    *,
    limit: int,
    offset: int,
    workspace_id: UUID,
) -> tuple[list[WorkflowResponse], int]:
    """Return workflows ordered by name and descending version."""
    scoped = select(Workflow).where(Workflow.workspace_id == workspace_id)
    total = session.scalar(select(func.count()).select_from(scoped.subquery())) or 0
    records = session.scalars(
        scoped.order_by(Workflow.name.asc(), Workflow.version.desc()).offset(offset).limit(limit)
    ).all()
    return [workflow_response(record) for record in records], total


def workflow_response(record: Workflow) -> WorkflowResponse:
    """Convert a persistence model into the public response contract."""
    return WorkflowResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        version=record.version,
        workflow_definition=WorkflowDefinition.model_validate(record.workflow_definition),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def validate_request_schema(request: WorkflowCreateRequest) -> WorkflowDefinition:
    """Convert an API request model into the provider-neutral domain contract."""
    return WorkflowDefinition.model_validate(request.model_dump(mode="python"))
