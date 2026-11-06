from uuid import uuid4

import agentforge.tools as tool_api
import pytest
from agentforge.domain.agents.contracts import AgentCapability
from agentforge.domain.workflows.models import WorkflowEvent, WorkflowEventType
from agentforge.tools import (
    CALCULATOR_TOOL,
    DEFAULT_TOOL_REGISTRY,
    ToolDefinition,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolExecutor,
    ToolRegistry,
)


def test_tool_package_exports_expected_public_api() -> None:
    assert hasattr(tool_api, "ToolExecutor")
    assert hasattr(tool_api, "ToolRegistry")
    assert hasattr(tool_api, "DEFAULT_TOOL_REGISTRY")
    assert tool_api.DEFAULT_TOOL_REGISTRY.get_by_id("calculator") is not None


def test_tool_definition_model_validates_basic_contract() -> None:
    tool = ToolDefinition(
        tool_id="sample_tool",
        name="sample_tool",
        description="Example tool",
        required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
    )

    assert tool.tool_id == "sample_tool"
    assert tool.enabled is True
    assert tool.required_capabilities == {AgentCapability.ANALYZE_SUPPLIED_DATA}


def test_tool_registry_rejects_duplicate_ids_and_names() -> None:
    registry = ToolRegistry()
    tool = ToolDefinition(
        tool_id="sample_tool",
        name="Sample Tool",
        description="Example tool",
    )
    registry.register(tool)

    with pytest.raises(ValueError):
        registry.register(tool.model_copy(update={"tool_id": "sample_tool_2"}))

    with pytest.raises(ValueError):
        registry.register(
            tool.model_copy(update={"tool_id": "sample_tool_3", "name": "Sample Tool"})
        )


def test_default_tool_registry_exposes_tools_by_capability() -> None:
    tools = DEFAULT_TOOL_REGISTRY.list_tools_for_capability(AgentCapability.ANALYZE_SUPPLIED_DATA)
    tool_ids = {tool.tool_id for tool in tools}

    assert {"text_analysis", "json_inspection", "calculator"}.issubset(tool_ids)


def test_executor_runs_safe_tool_and_rejects_missing_capability() -> None:
    executor = ToolExecutor(DEFAULT_TOOL_REGISTRY)
    request = ToolExecutionRequest(
        tool_id="calculator",
        agent_id="analyst-1",
        arguments={"operation": "add", "left": 2, "right": 3},
        agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
    )

    result = executor.execute(request)
    assert result.status == ToolExecutionStatus.SUCCEEDED
    assert result.output is not None
    assert result.output.output["result"] == 5

    unauthorized = ToolExecutionRequest(
        tool_id="calculator",
        agent_id="analyst-2",
        arguments={"operation": "add", "left": 2, "right": 3},
        agent_capabilities=frozenset(),
    )
    denied = executor.execute(unauthorized)
    assert denied.status == ToolExecutionStatus.DENIED
    assert denied.error is not None and denied.error.code == "missing_capability"


def test_executor_rejects_disabled_tool_before_handler_invoke() -> None:
    disabled = CALCULATOR_TOOL.model_copy(update={"enabled": False})
    registry = ToolRegistry([disabled])

    result = ToolExecutor(registry).execute(
        ToolExecutionRequest(
            tool_id="calculator",
            agent_id="analyst-1",
            arguments={"operation": "add", "left": 1, "right": 2},
            agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        )
    )

    assert result.status == ToolExecutionStatus.DENIED
    assert result.error is not None and result.error.code == "tool_disabled"


def test_executor_validates_output_and_size_limits() -> None:
    tool = ToolDefinition(
        tool_id="strict_tool",
        name="strict_tool",
        description="Reject malformed output",
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        output_size_limit=32,
        handler=lambda payload: {"value": "not-an-int"},
    )
    registry = ToolRegistry([tool])

    result = ToolExecutor(registry).execute(
        ToolExecutionRequest(
            tool_id="strict_tool",
            agent_id="analyst-1",
            arguments={"value": 1},
            agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        )
    )

    assert result.status == ToolExecutionStatus.FAILED
    assert result.error is not None and result.error.code == "invalid_output"

    oversized = ToolDefinition(
        tool_id="size_limited_tool",
        name="size_limited_tool",
        description="Reject oversized input",
        input_schema={
            "type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"],
            "additionalProperties": False,
        },
        input_size_limit=8,
        handler=lambda payload: {"value": payload["text"]},
    )
    size_result = ToolExecutor(ToolRegistry([oversized])).execute(
        ToolExecutionRequest(
            tool_id="size_limited_tool",
            agent_id="analyst-1",
            arguments={"text": "123456789"},
            agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        )
    )
    assert size_result.status == ToolExecutionStatus.FAILED
    assert size_result.error is not None and size_result.error.code == "invalid_input"


def test_executor_does_not_expose_raw_handler_exception_text() -> None:
    def failing_handler(payload: object) -> dict[str, object]:
        raise ValueError("sentinel-private-diagnostic")

    tool = ToolDefinition(
        tool_id="failing_tool",
        name="failing_tool",
        description="Raises a private diagnostic for this test.",
        handler=failing_handler,
    )
    result = ToolExecutor(ToolRegistry([tool])).execute(
        ToolExecutionRequest(
            tool_id="failing_tool",
            agent_id="analyst-1",
            arguments={},
            agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        )
    )

    assert result.status == ToolExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.details == {}
    assert "sentinel-private-diagnostic" not in result.model_dump_json()


def test_executor_enforces_size_limits_without_declared_schemas() -> None:
    calls = []
    tool = ToolDefinition(
        tool_id="schema_less_tool",
        name="schema_less_tool",
        description="Has explicit size limits without JSON schemas.",
        input_size_limit=8,
        handler=lambda payload: calls.append(payload) or {"ok": True},
    )

    result = ToolExecutor(ToolRegistry([tool])).execute(
        ToolExecutionRequest(
            tool_id="schema_less_tool",
            agent_id="analyst-1",
            arguments={"value": "too-large"},
            agent_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        )
    )

    assert result.status == ToolExecutionStatus.FAILED
    assert result.error is not None and result.error.code == "invalid_input"
    assert calls == []


def test_tool_execution_result_is_compatible_with_execution_event_records() -> None:
    result = ToolExecutionResult(
        tool_id="calculator",
        tool_name="calculator",
        tool_version="1.0.0",
        agent_id="analyst-1",
        status=ToolExecutionStatus.SUCCEEDED,
        output={"output": {"operation": "+", "result": 7}, "metadata": {}, "ok": True},
        metadata={"agent_capabilities": ["analyze_supplied_data"]},
    )
    assert result.tool_id == "calculator"
    assert result.tool_name == "calculator"
    assert result.occurred_at is not None

    event = WorkflowEvent(
        event_type=WorkflowEventType.WORKFLOW_STARTED,
        execution_id=uuid4(),
        metadata={
            "tool_id": result.tool_id,
            "tool_name": result.tool_name,
            "status": result.status.value,
        },
    )
    assert event.metadata["tool_id"] == "calculator"
