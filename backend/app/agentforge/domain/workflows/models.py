"""Pydantic contracts for deterministic workflow execution."""

import json
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agentforge.domain.agents.contracts import (
    AgentExecutionResult,
    AgentRole,
    JsonObject,
    JsonValue,
)

MAX_TASK_INPUT_BYTES = 10_000


class WorkflowContract(BaseModel):
    """Shared strict configuration for workflow contracts."""

    model_config = ConfigDict(extra="forbid", revalidate_instances="always")


class WorkflowStatus(StrEnum):
    """Lifecycle status of one in-memory workflow execution."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


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


class TaskExecutionResult(WorkflowContract):
    """The final state and optional agent result for one workflow task."""

    task_id: str = Field(min_length=1, max_length=100)
    agent_type: AgentRole
    status: TaskStatus
    agent_result: AgentExecutionResult | None = None
    error: WorkflowTaskError | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None


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
    started_at: datetime | None = None
    completed_at: datetime | None = None
