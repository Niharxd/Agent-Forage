"""Pydantic contracts for deterministic workflow execution."""

import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import ClassVar
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentforge.domain.agents.contracts import (
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentRole,
    JsonObject,
    JsonValue,
)

MAX_TASK_INPUT_BYTES = 10_000


class WorkflowStateTransitionError(ValueError):
    """Raised when a workflow or task status transition is not permitted."""


class WorkflowContract(BaseModel):
    """Shared strict configuration for workflow contracts."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class WorkflowStatus(StrEnum):
    """Lifecycle status of one in-memory workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(StrEnum):
    """Lifecycle status of one task in a workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    SKIPPED = "skipped"


class WorkflowEventType(StrEnum):
    """Structured lifecycle events emitted by the execution engine."""

    WORKFLOW_STARTED = "workflow_started"
    TASK_STARTED = "task_started"
    TASK_COMPLETED = "task_completed"
    TASK_FAILED = "task_failed"
    TASK_BLOCKED = "task_blocked"
    WORKFLOW_COMPLETED = "workflow_completed"
    WORKFLOW_FAILED = "workflow_failed"
    WORKFLOW_CANCELLATION_REQUESTED = "workflow_cancellation_requested"
    WORKFLOW_CANCELLED = "workflow_cancelled"
    TASK_SKIPPED = "task_skipped"
    EXECUTION_LIMIT_REACHED = "execution_limit_reached"


class WorkflowTask(WorkflowContract):
    """One bounded, declarative task assigned to a registered agent role."""

    task_id: str = Field(min_length=1, max_length=100)
    agent_type: AgentRole
    input_data: JsonObject = Field(default_factory=dict)
    dependency_ids: list[str] = Field(default_factory=list, max_length=25)
    description: str | None = Field(default=None, max_length=10_000)
    review_criteria: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("input_data")
    @classmethod
    def input_data_must_be_bounded(cls, value: JsonObject) -> JsonObject:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        if len(encoded) > MAX_TASK_INPUT_BYTES:
            raise ValueError(f"input_data must not exceed {MAX_TASK_INPUT_BYTES} bytes")
        return value

    @field_validator("review_criteria")
    @classmethod
    def review_criteria_must_be_valid(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("review criteria must not be blank")
        if any(len(value) > 500 for value in normalized):
            raise ValueError("review criteria must not exceed 500 characters")
        return normalized


class WorkflowDefinition(WorkflowContract):
    """A declarative workflow definition; it contains no executable code."""

    name: str = Field(default="workflow", min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)
    tasks: list[WorkflowTask] = Field(min_length=1)


class WorkflowTaskError(WorkflowContract):
    """Structured failure information for a failed or blocked task."""

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1_000)
    details: JsonObject = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @model_validator(mode="after")
    def timestamp_must_be_timezone_aware(self) -> "WorkflowTaskError":
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("workflow task error timestamps must be timezone-aware")
        return self


class TaskExecutionResult(WorkflowContract):
    """The final state and optional agent result for one workflow task."""

    task_id: str = Field(min_length=1, max_length=100)
    agent_type: AgentRole
    status: TaskStatus
    agent_result: AgentExecutionResult | None = None
    error: WorkflowTaskError | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    _ALLOWED_TRANSITIONS: ClassVar[dict[TaskStatus, set[TaskStatus]]] = {
        TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.BLOCKED, TaskStatus.SKIPPED},
        TaskStatus.RUNNING: {TaskStatus.COMPLETED, TaskStatus.FAILED},
        TaskStatus.COMPLETED: set(),
        TaskStatus.FAILED: set(),
        TaskStatus.BLOCKED: set(),
        TaskStatus.SKIPPED: set(),
    }

    def transition_to(self, new_status: TaskStatus) -> None:
        """Validate and apply one task lifecycle transition."""
        if new_status not in self._ALLOWED_TRANSITIONS[self.status]:
            raise WorkflowStateTransitionError(
                f"Task {self.task_id!r} cannot transition from "
                f"{self.status.value!r} to {new_status.value!r}."
            )
        self.status = new_status


class WorkflowEvent(WorkflowContract):
    """An immutable lifecycle event compatible with DB event fields."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: WorkflowEventType
    execution_id: UUID
    task_id: str | None = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    from_status: str | None = None
    to_status: str | None = None
    reason: str | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def timestamp_must_be_timezone_aware(self) -> "WorkflowEvent":
        if self.timestamp.tzinfo is None or self.timestamp.utcoffset() is None:
            raise ValueError("workflow event timestamps must be timezone-aware")
        return self

    @property
    def occurred_at(self) -> datetime:
        """Return the matching timestamp field used by the persistence event model."""
        return self.timestamp

    @property
    def details(self) -> JsonObject:
        """Return JSON event details using the persistence model's field name."""
        details: dict[str, JsonValue] = dict(self.metadata)
        if self.task_id is not None:
            details["task_id"] = self.task_id
        return details


class WorkflowExecution(WorkflowContract):
    """Complete in-memory execution state, results, and append-only event history."""

    execution_id: UUID = Field(default_factory=uuid4)
    workflow: WorkflowDefinition
    status: WorkflowStatus = WorkflowStatus.PENDING
    task_results: dict[str, TaskExecutionResult]
    events: list[WorkflowEvent] = Field(default_factory=list)
    execution_order: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    completed_at: datetime | None = None
    cancellation_requested: bool = False

    _ALLOWED_TRANSITIONS: ClassVar[dict[WorkflowStatus, set[WorkflowStatus]]] = {
        WorkflowStatus.PENDING: {WorkflowStatus.RUNNING, WorkflowStatus.CANCELLED},
        WorkflowStatus.RUNNING: {
            WorkflowStatus.COMPLETED,
            WorkflowStatus.FAILED,
            WorkflowStatus.CANCELLED,
        },
        WorkflowStatus.COMPLETED: set(),
        WorkflowStatus.FAILED: set(),
        WorkflowStatus.CANCELLED: set(),
    }

    def transition_to(self, new_status: WorkflowStatus) -> None:
        """Validate and apply one workflow lifecycle transition."""
        if new_status not in self._ALLOWED_TRANSITIONS[self.status]:
            raise WorkflowStateTransitionError(
                f"Workflow cannot transition from {self.status.value!r} to {new_status.value!r}."
            )
        self.status = new_status

    def snapshot(self) -> "WorkflowExecutionSnapshot":
        """Return a detached, serializable view of the current execution state."""
        return WorkflowExecutionSnapshot(
            execution_id=self.execution_id,
            workflow_name=self.workflow.name,
            status=self.status,
            created_at=self.created_at,
            started_at=self.started_at,
            completed_at=self.completed_at,
            task_results={
                task_id: result.model_copy(deep=True)
                for task_id, result in self.task_results.items()
            },
            events=[event.model_copy(deep=True) for event in self.events],
            execution_order=list(self.execution_order),
            cancellation_requested=self.cancellation_requested,
        )


class WorkflowExecutionSnapshot(WorkflowContract):
    """Detached, Pydantic-serializable execution state snapshot."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always", frozen=True)

    execution_id: UUID
    workflow_name: str
    status: WorkflowStatus
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    task_results: dict[str, TaskExecutionResult]
    events: list[WorkflowEvent]
    execution_order: list[str]
    cancellation_requested: bool = False

    @model_validator(mode="after")
    def snapshot_must_be_consistent(self) -> "WorkflowExecutionSnapshot":
        for timestamp in (self.created_at, self.started_at, self.completed_at):
            if timestamp is not None and (
                timestamp.tzinfo is None or timestamp.utcoffset() is None
            ):
                raise ValueError("workflow snapshot timestamps must be timezone-aware")
        task_statuses = {result.status for result in self.task_results.values()}
        if not self.task_results:
            raise ValueError("workflow snapshots must contain at least one task")
        for result in self.task_results.values():
            for timestamp in (result.started_at, result.completed_at):
                if timestamp is not None and (
                    timestamp.tzinfo is None or timestamp.utcoffset() is None
                ):
                    raise ValueError("task snapshot timestamps must be timezone-aware")
            if result.status == TaskStatus.PENDING:
                if result.started_at is not None or result.completed_at is not None:
                    raise ValueError("pending task snapshots cannot have timestamps")
                if result.agent_result is not None or result.error is not None:
                    raise ValueError("pending task snapshots cannot contain results or errors")
            elif result.status == TaskStatus.RUNNING:
                if result.started_at is None or result.completed_at is not None:
                    raise ValueError("running task snapshots require only a start timestamp")
                if result.agent_result is not None or result.error is not None:
                    raise ValueError("running task snapshots cannot contain results or errors")
            elif result.status == TaskStatus.COMPLETED:
                if result.started_at is None or result.completed_at is None:
                    raise ValueError("completed task snapshots require lifecycle timestamps")
                if (
                    result.agent_result is None
                    or result.agent_result.status != AgentExecutionStatus.SUCCEEDED
                    or result.error is not None
                ):
                    raise ValueError("completed task snapshots require a successful result")
            elif result.status == TaskStatus.FAILED:
                if result.completed_at is None or result.error is None:
                    raise ValueError("failed task snapshots require an error and completion time")
            elif result.status in {TaskStatus.BLOCKED, TaskStatus.SKIPPED}:
                if (
                    result.started_at is not None
                    or result.completed_at is None
                    or result.error is None
                    or result.agent_result is not None
                ):
                    raise ValueError("blocked or skipped task snapshots are inconsistent")
        if self.status == WorkflowStatus.PENDING:
            if self.started_at is not None or self.completed_at is not None:
                raise ValueError("pending workflow snapshots cannot have start or completion times")
            if task_statuses != {TaskStatus.PENDING}:
                raise ValueError("pending workflow snapshots must contain only pending tasks")
        elif self.status == WorkflowStatus.RUNNING:
            if self.started_at is None or self.completed_at is not None:
                raise ValueError("running workflow snapshots require only a start time")
        else:
            if self.completed_at is None:
                raise ValueError("terminal workflow snapshots must include completed_at")
            if task_statuses.intersection({TaskStatus.PENDING, TaskStatus.RUNNING}):
                raise ValueError("terminal workflow snapshots cannot contain active tasks")
            if self.status == WorkflowStatus.COMPLETED and task_statuses != {TaskStatus.COMPLETED}:
                raise ValueError("completed workflow snapshots must contain only completed tasks")
            if self.status == WorkflowStatus.FAILED and not task_statuses.intersection(
                {TaskStatus.FAILED, TaskStatus.BLOCKED, TaskStatus.SKIPPED}
            ):
                raise ValueError("failed workflow snapshots must contain a failed task")
        if any(task_id != result.task_id for task_id, result in self.task_results.items()):
            raise ValueError("task result keys must match their task IDs")
        if len(self.execution_order) != len(set(self.execution_order)):
            raise ValueError("execution_order must not contain duplicate task IDs")
        if any(task_id not in self.task_results for task_id in self.execution_order):
            raise ValueError("execution_order must contain only known task IDs")
        started_task_ids = {
            task_id
            for task_id, result in self.task_results.items()
            if result.started_at is not None
        }
        if set(self.execution_order) != started_task_ids:
            raise ValueError("execution_order must match tasks that started")
        return self
