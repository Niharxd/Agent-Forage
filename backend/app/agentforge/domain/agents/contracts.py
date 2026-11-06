"""Validated, provider-neutral contracts shared by AgentForge agents."""

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

AgentId = Annotated[
    str,
    Field(min_length=1, max_length=64, pattern=r"^[a-z][a-z0-9_-]*$"),
]
JsonObject = dict[str, JsonValue]


class AgentRole(StrEnum):
    """A specialized responsibility within an AgentForge workflow."""

    PLANNER = "planner"
    RESEARCHER = "researcher"
    ANALYST = "analyst"
    REVIEWER = "reviewer"


class AgentCapability(StrEnum):
    """A declared operation an agent can perform."""

    CREATE_PLAN = "create_plan"
    RESEARCH_SUPPLIED_INFORMATION = "research_supplied_information"
    ANALYZE_SUPPLIED_DATA = "analyze_supplied_data"
    REVIEW_AGAINST_CRITERIA = "review_against_criteria"


class AgentExecutionStatus(StrEnum):
    """Terminal status of one agent invocation."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class AgentErrorCode(StrEnum):
    """Stable categories for expected agent and contract failures."""

    INVALID_INPUT = "invalid_input"
    UNSUPPORTED_CAPABILITY = "unsupported_capability"
    EXECUTION_FAILURE = "execution_failure"
    TIMEOUT = "timeout"
    VALIDATION_FAILURE = "validation_failure"
    INTERNAL_AGENT_ERROR = "internal_agent_error"


class AgentContract(BaseModel):
    """Shared strict configuration for immutable agent contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class AgentIdentity(AgentContract):
    """Stable metadata and declared capabilities for an agent implementation."""

    agent_id: AgentId
    name: str = Field(min_length=1, max_length=100)
    role: AgentRole
    description: str = Field(min_length=1, max_length=500)
    supported_capabilities: frozenset[AgentCapability] = Field(min_length=1)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")


class PreviousAgentResult(AgentContract):
    """A compact, validated result from an earlier agent invocation."""

    agent_id: AgentId
    status: AgentExecutionStatus
    result_data: JsonObject = Field(default_factory=dict)
    summary: str = Field(min_length=1, max_length=4000)
    tool_output: JsonValue | None = None


class AgentInput(AgentContract):
    """Task-scoped input independent of HTTP requests and provider SDKs."""

    task_description: str = Field(min_length=1, max_length=10_000)
    execution_context: JsonObject = Field(default_factory=dict)
    input_data: JsonObject = Field(default_factory=dict)
    previous_results: list[PreviousAgentResult] = Field(default_factory=list)
    metadata: JsonObject = Field(default_factory=dict)
    requested_capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
    review_criteria: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("task_description")
    @classmethod
    def task_description_must_not_be_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("task_description must not be blank")
        return normalized

    @field_validator("review_criteria")
    @classmethod
    def review_criteria_must_not_be_blank(cls, values: list[str]) -> list[str]:
        normalized = [value.strip() for value in values]
        if any(not value for value in normalized):
            raise ValueError("review criteria must not be blank")
        if any(len(value) > 500 for value in normalized):
            raise ValueError("review criteria must not exceed 500 characters")
        return normalized


class AgentError(AgentContract):
    """Safe, structured information about an agent invocation failure."""

    code: AgentErrorCode
    message: str = Field(min_length=1, max_length=1000)
    details: JsonObject = Field(default_factory=dict)
    retryable: bool = False


class AgentOutput(AgentContract):
    """Validated result returned by one specialized agent."""

    agent_id: AgentId
    status: AgentExecutionStatus
    result_data: JsonObject = Field(default_factory=dict)
    summary: str = Field(min_length=1, max_length=4000)
    metadata: JsonObject = Field(default_factory=dict)
    error: AgentError | None = None

    @model_validator(mode="after")
    def error_must_match_status(self) -> "AgentOutput":
        if self.status == AgentExecutionStatus.FAILED and self.error is None:
            raise ValueError("failed agent outputs must include an error")
        if self.status == AgentExecutionStatus.SUCCEEDED and self.error is not None:
            raise ValueError("successful agent outputs cannot include an error")
        return self


class TokenUsage(AgentContract):
    """Provider-neutral token accounting when a provider reports usage."""

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    @property
    def total_tokens(self) -> int:
        """Return the sum of input and output tokens."""
        return self.input_tokens + self.output_tokens


class AgentExecutionResult(AgentContract):
    """Agent output with timing, optional usage, and invocation-level metadata."""

    status: AgentExecutionStatus
    output: AgentOutput
    execution_duration_ms: int = Field(ge=0)
    token_usage: TokenUsage | None = None
    error: AgentError | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def execution_fields_must_match_output(self) -> "AgentExecutionResult":
        if self.status != self.output.status:
            raise ValueError("execution status must match output status")
        if self.status == AgentExecutionStatus.FAILED:
            if self.error is None or self.error != self.output.error:
                raise ValueError("failed executions must match the output error")
        elif self.error is not None:
            raise ValueError("successful executions cannot include an error")
        return self
