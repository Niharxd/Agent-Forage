"""Provider-neutral tool contracts and execution models."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from agentforge.domain.agents.contracts import AgentCapability, JsonObject

ToolArgumentValue: TypeAlias = JsonValue


class ToolExecutionStatus(StrEnum):
    """Lifecycle status for a single tool invocation."""

    REQUESTED = "requested"
    AWAITING_APPROVAL = "awaiting_approval"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    DENIED = "denied"
    AMBIGUOUS = "ambiguous"


class ToolExecutionError(BaseModel):
    """Structured, safe information about a rejected or failed tool call."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=100)
    message: str = Field(min_length=1, max_length=1000)
    details: JsonObject = Field(default_factory=dict)


class ToolInput(BaseModel):
    """Generic validated input accepted by a tool implementation."""

    model_config = ConfigDict(extra="forbid")

    arguments: ToolArgumentValue = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def coerce_raw_input(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            if "arguments" in value or "metadata" in value:
                return value
            return {"arguments": value}
        return {"arguments": value}


class ToolOutput(BaseModel):
    """Generic validated output returned by a tool implementation."""

    model_config = ConfigDict(extra="forbid")

    output: ToolArgumentValue = Field(default_factory=dict)
    metadata: JsonObject = Field(default_factory=dict)
    ok: bool = True

    @model_validator(mode="before")
    @classmethod
    def coerce_raw_output(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            if "output" in value or "metadata" in value or "ok" in value:
                return value
            if (
                set(value).issubset({"result", "metadata", "ok"})
                and len(value) == 1
                and "result" in value
            ):
                return {
                    "output": value["result"],
                    "metadata": value.get("metadata", {}),
                    "ok": value.get("ok", True),
                }
            return {"output": value}
        return {"output": value}


class ToolDefinition(BaseModel):
    """Explicitly registered tool metadata and policy surface."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=500)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    input_schema: JsonObject = Field(default_factory=dict)
    output_schema: JsonObject = Field(default_factory=dict)
    required_capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
    enabled: bool = True
    input_size_limit: int = Field(default=10_000, gt=0)
    output_size_limit: int = Field(default=10_000, gt=0)
    execution_limits: JsonObject = Field(default_factory=dict)
    handler: Any | None = None

    @model_validator(mode="before")
    @classmethod
    def coerce_capabilities(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "required_capabilities" in value:
            capabilities = value["required_capabilities"]
            if capabilities is None:
                value = {**value, "required_capabilities": frozenset()}
            elif isinstance(capabilities, (str, AgentCapability)):
                value = {
                    **value,
                    "required_capabilities": frozenset({AgentCapability(capabilities)}),
                }
            elif isinstance(capabilities, (list, tuple, set, frozenset)):
                normalized = frozenset(AgentCapability(capability) for capability in capabilities)
                value = {**value, "required_capabilities": normalized}
        return value

    @property
    def is_enabled(self) -> bool:
        return self.enabled


class ToolExecutionRequest(BaseModel):
    """Request to execute a registered tool under a given agent capability context."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1, max_length=64)
    agent_id: str = Field(min_length=1, max_length=64)
    arguments: ToolArgumentValue = Field(default_factory=dict)
    agent_capabilities: frozenset[AgentCapability] = Field(default_factory=frozenset)
    execution_id: str | None = Field(default=None, min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_execution_id: str | None = Field(default=None, min_length=1, max_length=128)
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def coerce_agent_capabilities(cls, value: Any) -> Any:
        if isinstance(value, Mapping) and "agent_capabilities" in value:
            capabilities = value["agent_capabilities"]
            if capabilities is None:
                value = {**value, "agent_capabilities": frozenset()}
            elif isinstance(capabilities, (str, AgentCapability)):
                value = {**value, "agent_capabilities": frozenset({AgentCapability(capabilities)})}
            elif isinstance(capabilities, (list, tuple, set, frozenset)):
                normalized = frozenset(AgentCapability(capability) for capability in capabilities)
                value = {**value, "agent_capabilities": normalized}
        return value


class ToolExecutionResult(BaseModel):
    """Safe result returned by the controlled executor."""

    model_config = ConfigDict(extra="forbid")

    tool_id: str = Field(min_length=1, max_length=64)
    tool_name: str = Field(min_length=1, max_length=100)
    tool_version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+$")
    agent_id: str = Field(min_length=1, max_length=64)
    workflow_execution_id: str | None = Field(default=None, min_length=1, max_length=128)
    task_id: str | None = Field(default=None, min_length=1, max_length=128)
    status: ToolExecutionStatus
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int = Field(default=0, ge=0)
    output: ToolOutput | None = None
    error: ToolExecutionError | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_status_consistency(self) -> "ToolExecutionResult":
        if self.started_at is None:
            self.started_at = datetime.now(UTC)
        if self.completed_at is None:
            self.completed_at = self.started_at
        if self.status == ToolExecutionStatus.SUCCEEDED and self.output is None:
            raise ValueError("successful tool executions must include output")
        if self.status in {
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.DENIED,
            ToolExecutionStatus.AMBIGUOUS,
        }:
            if self.error is None:
                raise ValueError("failed or denied tool executions must include an error")
        if self.status == ToolExecutionStatus.SUCCEEDED and self.error is not None:
            raise ValueError("successful tool executions cannot include an error")
        if self.completed_at.tzinfo is None or self.completed_at.utcoffset() is None:
            raise ValueError("completed_at must be timezone-aware")
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        return self

    @property
    def occurred_at(self) -> datetime | None:
        if self.completed_at is not None:
            return self.completed_at
        return self.started_at


class ToolExecutionRecord(ToolExecutionResult):
    """Compatibility alias for persistence-oriented callers."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = Field(default=None, min_length=1, max_length=128)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def safe_status(self) -> ToolExecutionStatus:
        return self.status
