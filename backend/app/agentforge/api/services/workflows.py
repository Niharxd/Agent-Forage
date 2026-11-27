"""Persistence operations for versioned workflow definitions."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentforge.api.schemas import (
    WorkflowCreateRequest,
    WorkflowMetadataUpdateRequest,
    WorkflowResponse,
)
from agentforge.api.services.executions import ExecutionRepository
from agentforge.domain.models import Workflow, WorkflowExecution, Workspace
from agentforge.domain.workflows.models import WorkflowDefinition, WorkflowExecutionSnapshot


class WorkflowVersionConflict(Exception):
    """Raised when a concurrently-created workflow version violates uniqueness."""


WorkflowFilter = Literal["active", "archived", "all"]


def _workflow_execution_summary(
    session: Session,
    workflow: Workflow,
) -> tuple[int, datetime | None]:
    count, last_execution_at = session.execute(
        select(func.count(WorkflowExecution.id), func.max(WorkflowExecution.created_at)).where(
            WorkflowExecution.workflow_id == workflow.id,
            WorkflowExecution.workspace_id == workflow.workspace_id,
        )
    ).one()
    return count, last_execution_at


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
        workflow_response(record)
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
    execution_count, last_execution_at = _workflow_execution_summary(session, record)
    return workflow_response(
        record,
        execution_count=execution_count,
        last_execution_at=last_execution_at,
    )


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
    if record is None:
        return None
    execution_count, last_execution_at = _workflow_execution_summary(session, record)
    return workflow_response(
        record,
        execution_count=execution_count,
        last_execution_at=last_execution_at,
    )


def list_workflows(
    session: Session,
    *,
    limit: int,
    offset: int,
    workspace_id: UUID,
    sort: Literal["name", "updated"] = "name",
    search: str | None = None,
    status: WorkflowFilter = "active",
) -> tuple[list[WorkflowResponse], int]:
    """Return filtered workspace workflows ordered by name or most recent update."""
    filters = [Workflow.workspace_id == workspace_id]
    if status == "active":
        filters.append(Workflow.archived_at.is_(None))
    elif status == "archived":
        filters.append(Workflow.archived_at.is_not(None))
    if search and search.strip():
        escaped_search = (
            search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        search_pattern = f"%{escaped_search}%"
        filters.append(
            or_(
                Workflow.name.ilike(search_pattern, escape="\\"),
                Workflow.description.ilike(search_pattern, escape="\\"),
            )
        )
    total = session.scalar(select(func.count(Workflow.id)).where(*filters)) or 0
    ordering = (
        (Workflow.updated_at.desc(), Workflow.id.desc())
        if sort == "updated"
        else (Workflow.name.asc(), Workflow.version.desc())
    )
    rows = session.execute(
        select(
            Workflow,
            func.count(WorkflowExecution.id),
            func.max(WorkflowExecution.created_at),
        )
        .outerjoin(
            WorkflowExecution,
            (WorkflowExecution.workflow_id == Workflow.id)
            & (WorkflowExecution.workspace_id == Workflow.workspace_id),
        )
        .where(*filters)
        .group_by(Workflow.id)
        .order_by(*ordering)
        .offset(offset)
        .limit(limit)
    ).all()
    return [
        workflow_response(
            record,
            execution_count=execution_count,
            last_execution_at=last_execution_at,
        )
        for record, execution_count, last_execution_at in rows
    ], total


def update_workflow_metadata(
    session: Session,
    workflow_id: UUID,
    *,
    workspace_id: UUID,
    user_id: UUID | None,
    changes: WorkflowMetadataUpdateRequest,
) -> WorkflowResponse | None:
    """Update only editable metadata on a workflow inside the authorized workspace."""
    record = session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id)
        .with_for_update()
    )
    if record is None:
        return None
    if "name" in changes.model_fields_set and changes.name is not None:
        record.name = changes.name
    if "description" in changes.model_fields_set:
        record.description = changes.description
    record.updated_by_user_id = user_id
    try:
        session.commit()
        session.refresh(record)
    except IntegrityError as exc:
        session.rollback()
        raise WorkflowVersionConflict from exc
    execution_count, last_execution_at = _workflow_execution_summary(session, record)
    return workflow_response(
        record,
        execution_count=execution_count,
        last_execution_at=last_execution_at,
    )


def set_workflow_archived(
    session: Session,
    workflow_id: UUID,
    *,
    workspace_id: UUID,
    user_id: UUID | None,
    archived: bool,
) -> WorkflowResponse | None:
    """Soft archive or restore a workflow without changing its definition or history."""
    record = session.scalar(
        select(Workflow)
        .where(Workflow.id == workflow_id, Workflow.workspace_id == workspace_id)
        .with_for_update()
    )
    if record is None:
        return None
    record.archived_at = datetime.now(UTC) if archived else None
    record.updated_by_user_id = user_id
    session.commit()
    session.refresh(record)
    execution_count, last_execution_at = _workflow_execution_summary(session, record)
    return workflow_response(
        record,
        execution_count=execution_count,
        last_execution_at=last_execution_at,
    )


def workflow_response(
    record: Workflow,
    *,
    execution_count: int = 0,
    last_execution_at: datetime | None = None,
) -> WorkflowResponse:
    """Convert a persistence model into the public response contract."""
    return WorkflowResponse(
        id=record.id,
        name=record.name,
        description=record.description,
        version=record.version,
        workflow_definition=WorkflowDefinition.model_validate(record.workflow_definition),
        created_at=record.created_at,
        updated_at=record.updated_at,
        status="archived" if record.archived_at is not None else "active",
        archived_at=record.archived_at,
        execution_count=execution_count,
        last_execution_at=last_execution_at,
    )


def validate_request_schema(request: WorkflowCreateRequest) -> WorkflowDefinition:
    """Convert an API request model into the provider-neutral domain contract."""
    return WorkflowDefinition.model_validate(request.model_dump(mode="python"))
