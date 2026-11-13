"""Public request and response schemas for workflow and execution APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentforge.domain.agents import AgentRole
from agentforge.domain.workflows.models import (
    TaskExecutionResult,
    TaskStatus,
    WorkflowDefinition,
    WorkflowEvent,
    WorkflowStatus,
)


class WorkflowCreateRequest(WorkflowDefinition):
    """A named workflow definition submitted for validation and persistence."""

    name: str = Field(min_length=1, max_length=200)


class WorkflowPrepareRequest(BaseModel):
    """A bounded natural-language task to plan into a pending workflow."""

    model_config = ConfigDict(extra="forbid")

    task_description: str = Field(min_length=1, max_length=10_000)

    @field_validator("task_description")
    @classmethod
    def task_description_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("task_description must not be blank")
        return normalized


class WorkflowResponse(BaseModel):
    """Persisted workflow definition and its assigned version."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    name: str
    description: str | None
    version: int
    workflow_definition: WorkflowDefinition
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    """Paginated workflow collection."""

    items: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowValidationIssueResponse(BaseModel):
    """Safe, machine-readable workflow validation issue."""

    code: str
    message: str
    location: list[str | int]


class WorkflowValidationResponse(BaseModel):
    """Result of validating a workflow without persisting or starting it."""

    valid: bool
    workflow: WorkflowDefinition | None = None
    issues: list[WorkflowValidationIssueResponse] = Field(default_factory=list)


class ExecutionPlanTask(BaseModel):
    """Safe task metadata used to visualize an execution's persisted plan."""

    task_id: str
    agent_type: AgentRole
    dependency_ids: list[str]
    status: TaskStatus


class ExecutionResponse(BaseModel):
    """Reconstructed execution state and task results from durable records."""

    model_config = ConfigDict(extra="forbid")

    execution_id: UUID
    workflow_name: str
    status: WorkflowStatus
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    task_results: dict[str, TaskExecutionResult]
    events: list[WorkflowEvent]
    execution_order: list[str]
    cancellation_requested: bool
    workflow_plan: list[ExecutionPlanTask] | None = None


class ExecutionListResponse(BaseModel):
    """Paginated collection of persisted executions."""

    items: list[ExecutionResponse]
    total: int
    limit: int
    offset: int


class WorkflowPrepareResponse(BaseModel):
    """Persisted workflow draft and its pending execution for operator review."""

    workflow: WorkflowResponse
    execution: ExecutionResponse


PageLimit = Annotated[int, Field(ge=1, le=100)]
