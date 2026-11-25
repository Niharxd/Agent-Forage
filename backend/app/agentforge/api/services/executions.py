"""Persistence operations for workflow execution snapshots."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session, selectinload

from agentforge.domain.models import (
    ApprovalRequest,
    ExecutionEvent,
    ExecutionStep,
    WorkflowExecution,
    Workspace,
)
from agentforge.domain.models.workflow import Workflow
from agentforge.domain.workflows.models import (
    TaskExecutionResult,
    TaskStatus,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowEventType,
    WorkflowExecutionSnapshot,
    WorkflowStatus,
)
from agentforge.workflow.engine import ExecutionNotFoundError


class ExecutionPersistenceError(RuntimeError):
    """Raised when an execution cannot be safely persisted or reconstructed."""


class ExecutionAlreadyExistsError(ExecutionPersistenceError):
    """Raised when an execution identifier is already durably registered."""


class ApprovalDecisionConflictError(ExecutionPersistenceError):
    """Raised when an approval has already expired or received a decision."""


_EVENT_DETAILS = {
    WorkflowEventType.WORKFLOW_CREATED: {"workflow_name", "task_count"},
    WorkflowEventType.WORKFLOW_STARTED: {"workflow_name", "task_count"},
    WorkflowEventType.TASK_STARTED: {"agent_type"},
    WorkflowEventType.TASK_RESUMED: {"agent_type"},
    WorkflowEventType.TASK_COMPLETED: {"agent_type", "execution_duration_ms"},
    WorkflowEventType.TASK_FAILED: {"agent_type"},
    WorkflowEventType.TASK_BLOCKED: {"blocked_by"},
    WorkflowEventType.EXECUTION_LIMIT_REACHED: {"maximum_steps"},
    WorkflowEventType.TASK_TOOL_EXECUTION_STARTED: {"tool_id"},
    WorkflowEventType.TASK_TOOL_EXECUTION_COMPLETED: {"tool_id", "status"},
    WorkflowEventType.TASK_TOOL_EXECUTION_FAILED: {"tool_id", "status"},
    WorkflowEventType.TASK_APPROVAL_REJECTED: {"tool_id"},
}
_TERMINAL_WORKFLOW_STATUSES = {
    WorkflowStatus.COMPLETED,
    WorkflowStatus.FAILED,
    WorkflowStatus.CANCELLED,
}
_API_WORKFLOW_STATUSES = {
    WorkflowStatus.PENDING.value,
    WorkflowStatus.RUNNING.value,
    WorkflowStatus.WAITING_APPROVAL.value,
    WorkflowStatus.COMPLETED.value,
    WorkflowStatus.FAILED.value,
    WorkflowStatus.CANCELLED.value,
}


class ExecutionRepository:
    """Commit engine snapshots and reconstruct detached API-domain snapshots."""

    def __init__(self, session: Session) -> None:
        self._session = session
        # Repository methods return ORM records for immediate response mapping;
        # keep committed values available after the request session closes.
        self._session.expire_on_commit = False

    def create_execution(
        self,
        snapshot: WorkflowExecutionSnapshot,
        *,
        workflow_id: UUID,
        workflow_version: int,
        definition: WorkflowDefinition,
        original_task: str | None = None,
        workspace_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Atomically insert an execution, its initial steps, and its creation event."""
        try:
            workflow_statement = select(Workflow).where(Workflow.id == workflow_id)
            if workspace_id is not None:
                workflow_statement = workflow_statement.where(Workflow.workspace_id == workspace_id)
            workflow = self._session.scalar(workflow_statement)
            if workflow is None:
                raise ExecutionPersistenceError("The referenced workflow version does not exist.")
            if workspace_id is not None and workflow.workspace_id != workspace_id:
                raise ExecutionPersistenceError(
                    "The referenced workflow workspace is inconsistent."
                )
            if workflow.version != workflow_version:
                raise ExecutionPersistenceError("The referenced workflow version is inconsistent.")
            if self._session.get(WorkflowExecution, snapshot.execution_id) is not None:
                raise ExecutionAlreadyExistsError("The execution identifier is already in use.")

            record = WorkflowExecution(
                id=snapshot.execution_id,
                workflow_id=workflow_id,
                workspace_id=workflow.workspace_id,
                created_by_user_id=created_by_user_id or workflow.created_by_user_id,
                original_task=(
                    original_task
                    if original_task is not None
                    else definition.description or definition.name
                ),
                status=snapshot.status.value,
                plan_version=workflow_version,
                started_at=snapshot.started_at,
                completed_at=snapshot.completed_at,
                created_at=snapshot.created_at,
            )
            self._session.add(record)
            self._session.flush()
            self._session.add_all(
                [
                    ExecutionStep(
                        execution_id=snapshot.execution_id,
                        task_id=task.task_id,
                        attempt_number=1,
                        agent_type=task.agent_type.value,
                        status=snapshot.task_results[task.task_id].status.value,
                        input_data=task.input_data,
                        output_data=snapshot.task_results[task.task_id].model_dump(mode="json"),
                    )
                    for task in definition.tasks
                ]
            )
            self._insert_events(
                snapshot.events,
                actor=f"user:{actor_user_id}" if actor_user_id is not None else "system",
            )
            self._session.commit()
        except ExecutionPersistenceError:
            self._session.rollback()
            raise
        except Exception as exc:
            self._session.rollback()
            raise ExecutionPersistenceError("The initial execution transaction failed.") from exc

    def synchronize_execution(
        self,
        snapshot: WorkflowExecutionSnapshot,
        *,
        workspace_id: UUID | None = None,
        actor_user_id: UUID | None = None,
    ) -> None:
        """Persist the next state and its newly appended audit events atomically."""
        try:
            execution_statement = select(WorkflowExecution).where(
                WorkflowExecution.id == snapshot.execution_id
            )
            if workspace_id is not None:
                execution_statement = execution_statement.where(
                    WorkflowExecution.workspace_id == workspace_id
                )
            record = self._session.scalar(execution_statement.with_for_update())
            if record is None:
                raise ExecutionPersistenceError("The durable execution record is missing.")

            last_event = self._session.scalar(
                select(ExecutionEvent)
                .where(ExecutionEvent.execution_id == snapshot.execution_id)
                .order_by(ExecutionEvent.sequence_number.desc())
                .limit(1)
            )
            current_sequence = last_event.sequence_number if last_event is not None else 0
            if len(snapshot.events) <= current_sequence:
                self._session.rollback()
                return
            if current_sequence and not self._event_matches(
                snapshot.events[current_sequence - 1],
                last_event,
            ):
                raise ExecutionPersistenceError("The durable event history is inconsistent.")

            steps = self._session.scalars(
                select(ExecutionStep).where(
                    ExecutionStep.execution_id == snapshot.execution_id,
                    ExecutionStep.attempt_number == 1,
                )
            ).all()
            steps_by_task = {step.task_id: step for step in steps}
            if set(steps_by_task) != set(snapshot.task_results):
                raise ExecutionPersistenceError("The durable task records are incomplete.")

            record.status = snapshot.status.value
            record.started_at = snapshot.started_at
            record.completed_at = snapshot.completed_at
            if record.started_by_user_id is None and snapshot.started_at is not None:
                record.started_by_user_id = actor_user_id
            if record.cancelled_by_user_id is None and (
                snapshot.cancellation_requested or snapshot.status == WorkflowStatus.CANCELLED
            ):
                record.cancelled_by_user_id = actor_user_id
            if snapshot.status in _TERMINAL_WORKFLOW_STATUSES:
                final_event = snapshot.events[-1]
                record.terminal_reason = final_event.reason

            for task_id, result in snapshot.task_results.items():
                step = steps_by_task[task_id]
                step.status = result.status.value
                step.started_at = result.started_at
                step.completed_at = result.completed_at
                step.output_data = result.model_dump(mode="json")
                step.error_message = result.error.message if result.error else None

            self._insert_events(
                snapshot.events[current_sequence:],
                start_sequence=current_sequence + 1,
                actor=f"user:{actor_user_id}" if actor_user_id is not None else "system",
            )
            self._session.commit()
        except ExecutionPersistenceError:
            self._session.rollback()
            raise
        except Exception as exc:
            self._session.rollback()
            raise ExecutionPersistenceError("The execution state transaction failed.") from exc

    def get_execution(
        self,
        execution_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> WorkflowExecutionSnapshot:
        """Reconstruct a detached execution snapshot from PostgreSQL."""
        if workspace_id is None:
            legacy = self._session.scalar(
                select(Workspace).where(Workspace.slug == "legacy-operator")
            )
            workspace_id = legacy.id if legacy is not None else UUID(int=0)
        record = self._load_execution(execution_id, workspace_id=workspace_id)
        if record is None:
            raise ExecutionNotFoundError(f"Execution {execution_id} was not found.")
        return self._snapshot(record)

    def get_execution_details(
        self,
        execution_id: UUID,
        *,
        workspace_id: UUID | None = None,
    ) -> tuple[WorkflowExecutionSnapshot, WorkflowDefinition]:
        """Return persisted execution state and its validated workflow definition."""
        if workspace_id is None:
            legacy = self._session.scalar(
                select(Workspace).where(Workspace.slug == "legacy-operator")
            )
            workspace_id = legacy.id if legacy is not None else UUID(int=0)
        record = self._load_execution(execution_id, workspace_id=workspace_id)
        if record is None:
            raise ExecutionNotFoundError(f"Execution {execution_id} was not found.")
        if record.workflow is None:
            raise ExecutionPersistenceError(
                "The durable execution record is incomplete or invalid."
            )
        return (
            self._snapshot(record),
            WorkflowDefinition.model_validate(record.workflow.workflow_definition),
        )

    def create_approval_request(
        self,
        *,
        approval_id: UUID | None = None,
        execution_id: UUID,
        execution_step_id: UUID | None,
        tool_id: str | None = None,
        action_description: str,
        action_digest: str,
        safe_arguments: dict[str, Any],
    ) -> ApprovalRequest:
        """Create and persist a pending approval request bound to an execution."""
        approval = ApprovalRequest(
            id=approval_id or uuid4(),
            execution_id=execution_id,
            execution_step_id=execution_step_id,
            tool_id=tool_id,
            action_description=action_description,
            action_digest=action_digest,
            safe_arguments=safe_arguments,
            status="pending",
        )
        self._session.add(approval)
        self._session.flush()
        return approval

    def approve_approval_request(
        self,
        approval_id: UUID,
        *,
        execution_id: UUID | None = None,
        workspace_id: UUID | None = None,
        commit: bool = True,
    ) -> ApprovalRequest:
        """Mark a pending approval request as approved and record the review time."""
        approval = self._lock_approval_request(
            approval_id,
            execution_id=execution_id,
            workspace_id=workspace_id,
        )
        if approval is None:
            raise ExecutionPersistenceError(f"Approval request {approval_id} was not found.")
        if approval.status != "pending":
            raise ApprovalDecisionConflictError(
                f"Approval request {approval_id} is not pending (status={approval.status!r})."
            )
        if approval.expires_at <= datetime.now(UTC):
            approval.status = "expired"
            approval.reviewed_at = datetime.now(UTC)
            self._finish_approval_decision(commit=commit)
            raise ApprovalDecisionConflictError(f"Approval request {approval_id} has expired.")
        approval.status = "approved"
        approval.reviewed_at = datetime.now(UTC)
        self._finish_approval_decision(commit=commit)
        return approval

    def reject_approval_request(
        self,
        approval_id: UUID,
        *,
        execution_id: UUID | None = None,
        workspace_id: UUID | None = None,
        commit: bool = True,
    ) -> ApprovalRequest:
        """Mark a pending approval request as rejected and record the review time."""
        approval = self._lock_approval_request(
            approval_id,
            execution_id=execution_id,
            workspace_id=workspace_id,
        )
        if approval is None:
            raise ExecutionPersistenceError(f"Approval request {approval_id} was not found.")
        if approval.status != "pending":
            raise ApprovalDecisionConflictError(
                f"Approval request {approval_id} is not pending (status={approval.status!r})."
            )
        if approval.expires_at <= datetime.now(UTC):
            approval.status = "expired"
            approval.reviewed_at = datetime.now(UTC)
            self._finish_approval_decision(commit=commit)
            raise ApprovalDecisionConflictError(f"Approval request {approval_id} has expired.")
        approval.status = "rejected"
        approval.reviewed_at = datetime.now(UTC)
        self._finish_approval_decision(commit=commit)
        return approval

    def _lock_approval_request(
        self,
        approval_id: UUID,
        *,
        execution_id: UUID | None,
        workspace_id: UUID | None,
    ) -> ApprovalRequest | None:
        if (execution_id is None) != (workspace_id is None):
            raise ValueError("execution_id and workspace_id must be provided together.")
        if execution_id is None or workspace_id is None:
            statement = select(ApprovalRequest).where(ApprovalRequest.id == approval_id)
        else:
            statement = self._approval_statement(
                execution_id=execution_id,
                workspace_id=workspace_id,
            ).where(ApprovalRequest.id == approval_id)
        return self._session.scalar(statement.with_for_update(of=ApprovalRequest))

    def expire_approval_request(
        self,
        approval_id: UUID,
        *,
        execution_id: UUID,
        workspace_id: UUID,
        commit: bool = True,
    ) -> ApprovalRequest:
        """Mark a still-pending approval as expired."""
        approval = self._session.scalar(
            self._approval_statement(
                execution_id=execution_id,
                workspace_id=workspace_id,
            )
            .where(ApprovalRequest.id == approval_id)
            .with_for_update(of=ApprovalRequest)
        )
        if approval is None:
            raise ExecutionPersistenceError(f"Approval request {approval_id} was not found.")
        if approval.status == "pending":
            approval.status = "expired"
            approval.reviewed_at = datetime.now(UTC)
            self._finish_approval_decision(commit=commit)
        return approval

    def _finish_approval_decision(self, *, commit: bool) -> None:
        try:
            if commit:
                self._session.commit()
            else:
                self._session.flush()
        except Exception as exc:
            self._session.rollback()
            raise ExecutionPersistenceError("Could not persist approval decision.") from exc

    def get_pending_approval_requests(self, *, execution_id: UUID) -> list[ApprovalRequest]:
        """Return all pending approval requests for an execution."""
        workspace_id = self._session.scalar(
            select(WorkflowExecution.workspace_id)
            .join(
                Workflow,
                (WorkflowExecution.workflow_id == Workflow.id)
                & (WorkflowExecution.workspace_id == Workflow.workspace_id),
            )
            .where(WorkflowExecution.id == execution_id)
        )
        if workspace_id is None:
            return []
        self._expire_pending_approvals(
            execution_id=execution_id,
            workspace_id=workspace_id,
        )
        return list(
            self._session.scalars(
                self._approval_statement(
                    execution_id=execution_id,
                    workspace_id=workspace_id,
                ).where(ApprovalRequest.status == "pending")
            )
        )

    def _expire_pending_approvals(self, *, execution_id: UUID, workspace_id: UUID) -> None:
        now = datetime.now(UTC)
        stale = list(
            self._session.scalars(
                self._approval_statement(
                    execution_id=execution_id,
                    workspace_id=workspace_id,
                ).where(
                    ApprovalRequest.status == "pending",
                    ApprovalRequest.expires_at <= now,
                )
            )
        )
        if stale:
            for approval in stale:
                approval.status = "expired"
                approval.reviewed_at = now
            self._session.flush()

    def get_approval_requests(
        self,
        *,
        execution_id: UUID,
        workspace_id: UUID,
    ) -> list[ApprovalRequest]:
        """Return approval rows for one execution, newest first."""
        self._expire_pending_approvals(execution_id=execution_id, workspace_id=workspace_id)
        return list(
            self._session.scalars(
                self._approval_statement(
                    execution_id=execution_id,
                    workspace_id=workspace_id,
                ).order_by(ApprovalRequest.requested_at.desc())
            )
        )

    def get_approval_for_execution(
        self,
        approval_id: UUID,
        *,
        execution_id: UUID,
        workspace_id: UUID,
    ) -> ApprovalRequest | None:
        """Return an approval only when its execution and workflow share the workspace."""
        return self._session.scalar(
            self._approval_statement(
                execution_id=execution_id,
                workspace_id=workspace_id,
            ).where(ApprovalRequest.id == approval_id)
        )

    @staticmethod
    def _approval_statement(*, execution_id: UUID, workspace_id: UUID):
        return (
            select(ApprovalRequest)
            .join(
                WorkflowExecution,
                ApprovalRequest.execution_id == WorkflowExecution.id,
            )
            .join(
                Workflow,
                (Workflow.id == WorkflowExecution.workflow_id)
                & (Workflow.workspace_id == WorkflowExecution.workspace_id),
            )
            .outerjoin(
                ExecutionStep,
                ApprovalRequest.execution_step_id == ExecutionStep.id,
            )
            .where(
                ApprovalRequest.execution_id == execution_id,
                WorkflowExecution.workspace_id == workspace_id,
                Workflow.workspace_id == workspace_id,
                or_(
                    ApprovalRequest.execution_step_id.is_(None),
                    ExecutionStep.execution_id == WorkflowExecution.id,
                ),
            )
        )

    def get_execution_step_id(self, *, execution_id: UUID, task_id: str) -> UUID | None:
        """Resolve a stable persisted task step for binding approval requests."""
        return self._session.scalar(
            select(ExecutionStep.id).where(
                ExecutionStep.execution_id == execution_id,
                ExecutionStep.task_id == task_id,
                ExecutionStep.attempt_number == 1,
            )
        )

    def get_approval_request_by_id(self, approval_id: UUID) -> ApprovalRequest | None:
        """Return an approval request by its identifier, or None if absent."""
        return self._session.get(ApprovalRequest, approval_id)

    def list_executions(
        self,
        *,
        limit: int,
        offset: int,
        status: WorkflowStatus | None = None,
        search: str | None = None,
        workspace_id: UUID | None = None,
    ) -> tuple[list[WorkflowExecutionSnapshot], int]:
        """Return filtered persisted executions in newest-first paginated order."""
        if workspace_id is None:
            legacy = self._session.scalar(
                select(Workspace).where(Workspace.slug == "legacy-operator")
            )
            if legacy is None:
                return [], 0
            workspace_id = legacy.id
        filters = [WorkflowExecution.status.in_(_API_WORKFLOW_STATUSES)]
        filters.append(WorkflowExecution.workspace_id == workspace_id)
        if status is not None:
            filters.append(WorkflowExecution.status == status.value)
        if search and search.strip():
            escaped_search = (
                search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            search_pattern = f"%{escaped_search}%"
            filters.append(
                or_(
                    cast(WorkflowExecution.id, String).ilike(search_pattern, escape="\\"),
                    Workflow.name.ilike(search_pattern, escape="\\"),
                )
            )

        executions_query = (
            select(WorkflowExecution)
            .join(
                Workflow,
                (WorkflowExecution.workflow_id == Workflow.id)
                & (WorkflowExecution.workspace_id == Workflow.workspace_id),
            )
            .where(*filters)
        )
        total = (
            self._session.scalar(
                select(func.count())
                .select_from(WorkflowExecution)
                .join(
                    Workflow,
                    (WorkflowExecution.workflow_id == Workflow.id)
                    & (WorkflowExecution.workspace_id == Workflow.workspace_id),
                )
                .where(*filters)
            )
            or 0
        )
        records = self._session.scalars(
            executions_query.options(
                selectinload(WorkflowExecution.workflow),
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.events),
            )
            .order_by(WorkflowExecution.created_at.desc(), WorkflowExecution.id.desc())
            .offset(offset)
            .limit(limit)
        ).all()
        return [self._snapshot(record) for record in records], total

    def _load_execution(
        self,
        execution_id: UUID,
        *,
        workspace_id: UUID,
    ) -> WorkflowExecution | None:
        return self._session.scalar(
            select(WorkflowExecution)
            .options(
                selectinload(WorkflowExecution.workflow),
                selectinload(WorkflowExecution.steps),
                selectinload(WorkflowExecution.events),
            )
            .join(
                Workflow,
                (WorkflowExecution.workflow_id == Workflow.id)
                & (WorkflowExecution.workspace_id == Workflow.workspace_id),
            )
            .where(
                WorkflowExecution.id == execution_id,
                WorkflowExecution.workspace_id == workspace_id,
            )
        )

    def _insert_events(
        self,
        events: list[WorkflowEvent],
        *,
        start_sequence: int = 1,
        actor: str = "system",
    ) -> None:
        self._session.add_all(
            [
                ExecutionEvent(
                    execution_id=event.execution_id,
                    sequence_number=sequence,
                    event_type=event.event_type.value,
                    actor=actor,
                    from_status=event.from_status,
                    to_status=event.to_status,
                    reason=event.reason,
                    details=self._safe_event_details(event),
                    occurred_at=event.timestamp,
                )
                for sequence, event in enumerate(events, start=start_sequence)
            ]
        )

    @staticmethod
    def _safe_event_details(event: WorkflowEvent) -> dict[str, Any]:
        details: dict[str, Any] = {}
        if event.task_id is not None:
            details["task_id"] = event.task_id

        allowed = _EVENT_DETAILS.get(event.event_type, set())
        for key in allowed:
            value = event.metadata.get(key)
            if isinstance(value, (str, int, float, bool)):
                details[key] = value
            elif (
                key == "blocked_by"
                and isinstance(value, list)
                and all(isinstance(item, str) for item in value)
            ):
                details[key] = value
        return details

    @staticmethod
    def _event_matches(event: WorkflowEvent, record: ExecutionEvent) -> bool:
        return (
            event.event_type.value == record.event_type
            and event.timestamp == record.occurred_at
            and event.task_id == (record.details or {}).get("task_id")
        )

    def _snapshot(self, record: WorkflowExecution) -> WorkflowExecutionSnapshot:
        try:
            if record.workflow is None:
                raise ValueError("execution workflow reference is missing")
            if record.plan_version != record.workflow.version:
                raise ValueError("execution workflow version is inconsistent")
            definition = WorkflowDefinition.model_validate(record.workflow.workflow_definition)
            status = WorkflowStatus(record.status)
            events = sorted(
                record.events,
                key=lambda event: (event.sequence_number, event.occurred_at, str(event.id)),
            )
            if [event.sequence_number for event in events] != list(range(1, len(events) + 1)):
                raise ValueError("execution event sequence is incomplete")

            steps_by_task = {
                step.task_id: step
                for step in sorted(record.steps, key=lambda step: step.attempt_number)
                if step.attempt_number == 1
            }
            if set(steps_by_task) != {task.task_id for task in definition.tasks}:
                raise ValueError("execution task records do not match its workflow")
            if any(
                steps_by_task[task.task_id].agent_type != task.agent_type.value
                for task in definition.tasks
            ):
                raise ValueError("execution task roles do not match its workflow")
            task_results = {
                task.task_id: self._task_result(steps_by_task[task.task_id], task.agent_type.value)
                for task in definition.tasks
            }
            workflow_events = [self._workflow_event(event, record.id) for event in events]
            execution_order = [
                event.task_id
                for event in workflow_events
                if event.event_type == WorkflowEventType.TASK_STARTED and event.task_id is not None
            ]
            cancellation_requested = any(
                event.event_type == WorkflowEventType.WORKFLOW_CANCELLATION_REQUESTED
                for event in workflow_events
            )
            return WorkflowExecutionSnapshot(
                execution_id=record.id,
                workflow_name=record.workflow.name,
                status=status,
                created_at=record.created_at,
                started_at=record.started_at,
                completed_at=record.completed_at,
                task_results=task_results,
                events=workflow_events,
                execution_order=execution_order,
                cancellation_requested=cancellation_requested,
            )
        except (TypeError, ValueError, KeyError) as exc:
            raise ExecutionPersistenceError(
                "The durable execution record is incomplete or invalid."
            ) from exc

    @staticmethod
    def _task_result(step: ExecutionStep, agent_type: str) -> TaskExecutionResult:
        if step.output_data is not None:
            result = TaskExecutionResult.model_validate(step.output_data)
            if result.status.value != step.status:
                raise ValueError("task result and durable task status disagree")
            return result
        if step.status in {TaskStatus.PENDING.value, TaskStatus.RUNNING.value}:
            return TaskExecutionResult(
                task_id=step.task_id,
                agent_type=agent_type,
                status=TaskStatus(step.status),
                started_at=step.started_at,
            )
        raise ValueError("terminal task result is missing")

    @staticmethod
    def _workflow_event(event: ExecutionEvent, execution_id: UUID) -> WorkflowEvent:
        details = dict(event.details or {})
        task_id = details.pop("task_id", None)
        event_type = WorkflowEventType(event.event_type)
        return WorkflowEvent(
            event_type=event_type,
            execution_id=execution_id,
            task_id=task_id,
            timestamp=event.occurred_at,
            from_status=event.from_status,
            to_status=event.to_status,
            reason=event.reason,
            metadata=details,
        )
