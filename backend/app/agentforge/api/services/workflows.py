"""Persistence operations for versioned workflow definitions."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentforge.api.schemas import WorkflowCreateRequest, WorkflowResponse
from agentforge.api.services.executions import ExecutionRepository
from agentforge.domain.models import Workflow
from agentforge.domain.workflows.models import WorkflowDefinition, WorkflowExecutionSnapshot


class WorkflowVersionConflict(Exception):
    """Raised when a concurrently-created workflow version violates uniqueness."""


def create_workflow(
    session: Session,
    definition: WorkflowDefinition,
) -> WorkflowResponse:
    """Persist one validated definition as the next version of its name."""
    record = _new_workflow_record(session, definition)
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
) -> WorkflowResponse:
    """Persist a planner-created workflow and its initial execution atomically."""
    record = _new_workflow_record(session, definition)
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
    )
    return saved_workflow


def _new_workflow_record(session: Session, definition: WorkflowDefinition) -> Workflow:
    latest_version = session.scalar(
        select(func.max(Workflow.version)).where(Workflow.name == definition.name)
    )
    return Workflow(
        name=definition.name,
        description=definition.description,
        version=(latest_version or 0) + 1,
        workflow_definition=definition.model_dump(mode="json"),
    )


def get_workflow(session: Session, workflow_id: UUID) -> WorkflowResponse | None:
    """Return a workflow response without exposing the SQLAlchemy object."""
    record = session.get(Workflow, workflow_id)
    return workflow_response(record) if record is not None else None


def list_workflows(
    session: Session,
    *,
    limit: int,
    offset: int,
) -> tuple[list[WorkflowResponse], int]:
    """Return workflows ordered by name and descending version."""
    total = session.scalar(select(func.count()).select_from(Workflow)) or 0
    records = session.scalars(
        select(Workflow)
        .order_by(Workflow.name.asc(), Workflow.version.desc())
        .offset(offset)
        .limit(limit)
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
