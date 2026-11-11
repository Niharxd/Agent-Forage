"""Public request and response schemas for workflow and execution APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

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


PageLimit = Annotated[int, Field(ge=1, le=100)]
