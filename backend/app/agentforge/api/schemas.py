"""Public request and response schemas for workflow and execution APIs."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

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
    status: str = "active"
    archived_at: datetime | None = None
    execution_count: int = 0
    last_execution_at: datetime | None = None


class WorkflowMetadataUpdateRequest(BaseModel):
    """Editable workflow metadata; security-sensitive fields are intentionally excluded."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=2_000)

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("name must not be null")
        normalized = value.strip()
        if not normalized:
            raise ValueError("name must not be blank")
        return normalized

    @field_validator("description")
    @classmethod
    def normalize_description(cls, value: str | None) -> str | None:
        normalized = value.strip() if value is not None else None
        return normalized or None

    @model_validator(mode="after")
    def at_least_one_field_must_be_provided(self) -> "WorkflowMetadataUpdateRequest":
        if not self.model_fields_set:
            raise ValueError("At least one editable metadata field is required.")
        return self


class WorkflowListResponse(BaseModel):
    """Paginated workflow collection."""

    items: list[WorkflowResponse]
    total: int
    limit: int
    offset: int


class WorkflowApprovalResponse(BaseModel):
    """Safe pending approval summary for a workspace dashboard."""

    approval_id: UUID
    execution_id: UUID
    workflow_name: str
    task_id: str | None = None
    tool_id: str | None = None
    action_description: str
    status: str
    requested_at: datetime
    expires_at: datetime


class WorkflowApprovalListResponse(BaseModel):
    """Paginated workspace-scoped pending approvals."""

    items: list[WorkflowApprovalResponse]
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


class ExecutionApprovalRequest(BaseModel):
    """Operator approval or rejection for a specific awaiting approval task."""

    model_config = ConfigDict(extra="forbid")

    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    reason: str | None = Field(default=None, min_length=1, max_length=500)


class ExecutionApprovalResponse(BaseModel):
    """Safe approval status without exposing action arguments or digests."""

    approval_id: UUID
    execution_id: UUID
    task_id: str | None = None
    tool_id: str | None = None
    action_description: str
    status: str
    requested_at: datetime
    expires_at: datetime
    reviewed_at: datetime | None = None


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


class RegistrationRequest(BaseModel):
    """Credentials used to create a public user account."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        local, separator, domain = normalized.rpartition("@")
        if (
            not separator
            or not local
            or not domain
            or "." not in domain
            or any(character.isspace() for character in normalized)
        ):
            raise ValueError("email must be a valid email address")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if (
            not any(character.islower() for character in value)
            or not any(character.isupper() for character in value)
            or not any(character.isdigit() for character in value)
        ):
            raise ValueError("password must contain upper, lower, and numeric characters")
        return value


class LoginRequest(BaseModel):
    """Credentials used to authenticate a public user account."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.strip().lower()


class UserResponse(BaseModel):
    """Safe public user representation."""

    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    email: str
    account_status: str
    email_verified_at: datetime | None
    last_login_at: datetime | None


class UserSessionResponse(UserResponse):
    """Public user identity and their personal workspace role."""

    workspace_role: str | None


class RegistrationResponse(BaseModel):
    """New user and automatically-created personal workspace."""

    user: UserResponse
    workspace_id: UUID


class LoginResponse(BaseModel):
    """Authenticated user and session expiry."""

    user: UserResponse
    expires_at: int
