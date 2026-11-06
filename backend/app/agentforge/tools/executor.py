"""Controlled execution for explicitly registered tools."""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from time import perf_counter

from agentforge.domain.agents.contracts import AgentCapability
from agentforge.tools.contracts import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolInput,
    ToolOutput,
)
from agentforge.tools.registry import ToolRegistry
from agentforge.tools.safe_tools import DEFAULT_TOOL_REGISTRY


class ToolExecutionFailure(RuntimeError):
    """Raised when a tool execution cannot be completed safely."""

    def __init__(self, result: ToolExecutionResult) -> None:
        self.result = result


class ToolExecutor:
    """Validate permissions, arguments, and outputs before invoking registered handlers."""

    def __init__(self, registry: ToolRegistry | None = None) -> None:
        self.registry = registry or DEFAULT_TOOL_REGISTRY

    def execute(
        self,
        request: ToolExecutionRequest | Mapping[str, object],
        *,
        agent_capabilities: Collection[AgentCapability | str] | None = None,
    ) -> ToolExecutionResult:
        started_at = perf_counter()
        execution_request = ToolExecutionRequest.model_validate(request)
        if agent_capabilities is not None:
            execution_request.agent_capabilities = frozenset(
                AgentCapability(capability) for capability in agent_capabilities
            )

        tool = self.registry.get_by_id(execution_request.tool_id)
        if tool is None:
            return self._result(
                execution_request,
                ToolExecutionStatus.DENIED,
                started_at,
                ToolExecutionError(
                    code="tool_not_found",
                    message="The requested tool is not registered.",
                    details={"tool_id": execution_request.tool_id},
                ),
            )

        if not tool.enabled:
            return self._result(
                execution_request,
                ToolExecutionStatus.DENIED,
                started_at,
                ToolExecutionError(
                    code="tool_disabled",
                    message="The requested tool is disabled.",
                    details={"tool_id": execution_request.tool_id},
                ),
            )

        if tool.handler is None or not callable(tool.handler):
            return self._result(
                execution_request,
                ToolExecutionStatus.FAILED,
                started_at,
                ToolExecutionError(
                    code="invalid_tool_handler",
                    message="The registered tool does not expose a trusted callable handler.",
                    details={"tool_id": execution_request.tool_id},
                ),
            )

        missing_capabilities = set(tool.required_capabilities) - set(
            execution_request.agent_capabilities
        )
        if missing_capabilities:
            return self._result(
                execution_request,
                ToolExecutionStatus.DENIED,
                started_at,
                ToolExecutionError(
                    code="missing_capability",
                    message="The agent is not permitted to call this tool.",
                    details={
                        "missing_capabilities": [
                            cap.value
                            for cap in sorted(missing_capabilities, key=lambda item: item.value)
                        ]
                    },
                ),
            )

        try:
            validated_input = ToolInput.model_validate({"arguments": execution_request.arguments})
            self._validate_against_schema(tool, validated_input.arguments, is_input=True)
        except (TypeError, ValueError):
            return self._result(
                execution_request,
                ToolExecutionStatus.FAILED,
                started_at,
                ToolExecutionError(
                    code="invalid_input",
                    message="The tool rejected the supplied input.",
                ),
            )

        try:
            output = tool.handler(validated_input.arguments)
            if output is None:
                raise ValueError("The tool did not return output.")
            validated_output = ToolOutput.model_validate(output)
            self._validate_against_schema(tool, validated_output.output, is_input=False)
            if self._payload_size(validated_output.output) > tool.output_size_limit:
                raise ValueError(f"Tool output exceeds the {tool.output_size_limit} byte limit.")

            timeout_ms = self._execution_timeout_ms(tool)
            elapsed_ms = max(0, round((perf_counter() - started_at) * 1000))
            if timeout_ms is not None and elapsed_ms > timeout_ms:
                raise TimeoutError(
                    f"Tool execution exceeded the configured time limit of {timeout_ms} ms."
                )
            return self._result(
                execution_request,
                ToolExecutionStatus.SUCCEEDED,
                started_at,
                output=validated_output,
            )
        except (TimeoutError, TypeError, ValueError) as exc:
            if isinstance(exc, TimeoutError):
                return self._result(
                    execution_request,
                    ToolExecutionStatus.FAILED,
                    started_at,
                    ToolExecutionError(
                        code="execution_timeout",
                        message="The tool exceeded the configured execution limit.",
                        details={
                            "limit_ms": self._execution_timeout_ms(tool),
                            "actual_ms": max(0, round((perf_counter() - started_at) * 1000)),
                        },
                    ),
                )
            return self._result(
                execution_request,
                ToolExecutionStatus.FAILED,
                started_at,
                ToolExecutionError(
                    code="invalid_output",
                    message="The tool returned an invalid result.",
                ),
            )

    def _validate_against_schema(
        self,
        tool: ToolDefinition,
        payload: object,
        *,
        is_input: bool,
    ) -> None:
        schema = tool.input_schema if is_input else tool.output_schema
        limit = tool.input_size_limit if is_input else tool.output_size_limit
        if self._payload_size(payload) > limit:
            raise ValueError(
                f"Tool {'input' if is_input else 'output'} exceeds the {limit} byte limit."
            )
        if not schema:
            return
        if schema.get("type") == "object":
            if not isinstance(payload, dict):
                raise ValueError("Expected an object payload.")
            required = set(schema.get("required", []))
            expected = set(schema.get("properties", {}).keys())
            missing = sorted(required - set(payload))
            if missing:
                raise ValueError(f"Missing required fields: {', '.join(missing)}")
            if schema.get("additionalProperties") is False:
                unexpected = sorted(set(payload) - expected)
                if unexpected:
                    raise ValueError(f"Unexpected fields: {', '.join(unexpected)}")
            property_schema = schema.get("properties", {})
            for key, value in payload.items():
                rules = property_schema.get(key, {})
                if not rules:
                    continue
                if "type" in rules and not self._matches_type(value, rules["type"]):
                    raise ValueError(f"Field {key!r} has an invalid type.")
                if "enum" in rules and value not in rules["enum"]:
                    raise ValueError(f"Field {key!r} has an invalid value.")
                if (
                    "maxLength" in rules
                    and isinstance(value, str)
                    and len(value) > rules["maxLength"]
                ):
                    raise ValueError(f"Field {key!r} exceeds its maximum length.")

    @staticmethod
    def _matches_type(value: object, expected: str) -> bool:
        mapping = {
            "string": isinstance(value, str),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "null": value is None,
        }
        return mapping.get(expected, True)

    @staticmethod
    def _payload_size(payload: object) -> int:
        encoded = json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return len(encoded)

    @staticmethod
    def _execution_timeout_ms(tool: ToolDefinition) -> int | None:
        execution_limits = tool.execution_limits or {}
        for key in ("max_execution_ms", "timeout_ms"):
            value = execution_limits.get(key)
            if value is None:
                continue
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(f"Tool execution limit {key!r} must be numeric.")
            return int(value)
        return None

    def _result(
        self,
        request: ToolExecutionRequest,
        status: ToolExecutionStatus,
        started_at: float,
        error: ToolExecutionError | None = None,
        *,
        output: ToolOutput | None = None,
    ) -> ToolExecutionResult:
        completed_at = datetime.now(UTC)
        duration_ms = max(0, round((perf_counter() - started_at) * 1000))
        tool = self.registry.get_by_id(request.tool_id)
        result = ToolExecutionResult(
            tool_id=request.tool_id,
            tool_name=tool.name if tool is not None else request.tool_id,
            tool_version=tool.version if tool is not None else "1.0.0",
            agent_id=request.agent_id,
            workflow_execution_id=request.workflow_execution_id,
            task_id=request.task_id,
            status=status,
            started_at=completed_at,
            completed_at=completed_at,
            duration_ms=duration_ms,
            output=output,
            error=error,
            metadata={
                **request.metadata,
                "agent_capabilities": [
                    cap.value
                    for cap in sorted(request.agent_capabilities, key=lambda item: item.value)
                ],
            },
        )
        return result

    def validate_request(
        self,
        request: ToolExecutionRequest | Mapping[str, object],
        *,
        agent_capabilities: Collection[AgentCapability | str] | None = None,
    ) -> None:
        """Reject an unsafe or malformed request without invoking its handler."""
        execution_request = ToolExecutionRequest.model_validate(request)
        if agent_capabilities is not None:
            execution_request.agent_capabilities = frozenset(
                AgentCapability(capability) for capability in agent_capabilities
            )

        tool = self.registry.get_by_id(execution_request.tool_id)
        if tool is None or not tool.enabled or tool.handler is None or not callable(tool.handler):
            raise ValueError("The requested tool is unavailable.")
        missing_capabilities = set(tool.required_capabilities) - set(
            execution_request.agent_capabilities
        )
        if missing_capabilities:
            raise ValueError("The agent is not permitted to call this tool.")
        validated_input = ToolInput.model_validate({"arguments": execution_request.arguments})
        if self._payload_size(validated_input.arguments) > tool.input_size_limit:
            raise ValueError("Tool input exceeds the configured size limit.")
        self._validate_against_schema(tool, validated_input.arguments, is_input=True)


__all__ = [
    "ToolExecutor",
    "ToolExecutionFailure",
]
