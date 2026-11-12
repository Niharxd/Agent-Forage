import json
from io import BytesIO
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
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
    wikipedia_search_handler,
)
from agentforge.tools.safe_tools import _WikipediaRedirectHandler
from agentforge.workflow.engine import WorkflowEngine


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


def install_fake_wikipedia_opener(
    monkeypatch: pytest.MonkeyPatch,
    *,
    response_body: bytes,
    redirect_location: str | None = None,
) -> tuple[list[object], list[float]]:
    requests: list[object] = []
    timeouts: list[float] = []

    class FakeOpener:
        def __init__(self, redirect_handler: _WikipediaRedirectHandler) -> None:
            self.redirect_handler = redirect_handler

        def open(self, request, *, timeout):
            requests.append(request)
            timeouts.append(timeout)
            if redirect_location is not None:
                redirected_request = self.redirect_handler.redirect_request(
                    request,
                    None,
                    302,
                    "Found",
                    {},
                    redirect_location,
                )
                if redirected_request is None:
                    raise HTTPError(request.full_url, 302, "Redirect rejected.", {}, BytesIO())
                requests.append(redirected_request)
            return BytesIO(response_body)

    def fake_build_opener(redirect_handler):
        assert isinstance(redirect_handler, _WikipediaRedirectHandler)
        return FakeOpener(redirect_handler)

    monkeypatch.setattr("agentforge.tools.safe_tools.build_opener", fake_build_opener)
    return requests, timeouts


def test_wikipedia_search_returns_limited_attributed_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_body = json.dumps(
        {
            "query": {
                "pages": {
                    "42": {
                        "pageid": 42,
                        "title": "Agent Forge",
                        "extract": "A" * 500,
                    }
                }
            }
        }
    ).encode()
    requests, timeouts = install_fake_wikipedia_opener(
        monkeypatch,
        response_body=response_body,
        redirect_location="https://en.wikipedia.org/w/api.php?continue=1",
    )

    result = wikipedia_search_handler({"query": "  agent forge  "})

    assert len(requests) == 2
    assert requests[0].get_method() == "GET"
    assert "gsrsearch=agent+forge" in requests[0].full_url
    assert requests[1].full_url == "https://en.wikipedia.org/w/api.php?continue=1"
    assert timeouts == [8]
    assert result["query"] == "agent forge"
    assert result["results"][0]["url"] == "https://en.wikipedia.org/?curid=42"
    assert len(result["results"][0]["extract"]) == 400


@pytest.mark.parametrize(
    "redirect_location",
    [
        "https://attacker.example/w/api.php?continue=1",
        "http://en.wikipedia.org/w/api.php?continue=1",
        "https://en.wikipedia.org:8443/w/api.php?continue=1",
        "https://127.0.0.1/w/api.php?continue=1",
        "https://en.wikipedia.org/other/path?continue=1",
        "ftp://en.wikipedia.org/w/api.php?continue=1",
    ],
)
def test_wikipedia_search_rejects_unsafe_redirect_without_network_calls(
    monkeypatch: pytest.MonkeyPatch,
    redirect_location: str,
) -> None:
    requests, timeouts = install_fake_wikipedia_opener(
        monkeypatch,
        response_body=b'{"query":{"pages":{}}}',
        redirect_location=redirect_location,
    )

    with pytest.raises(ValueError, match="temporarily unavailable"):
        wikipedia_search_handler({"query": "agent safety"})

    assert len(requests) == 1
    assert requests[0].full_url.startswith("https://en.wikipedia.org/w/api.php?")
    assert timeouts == [8]


@pytest.mark.parametrize("query", ["", " " * 2, "x" * 201, 123])
def test_wikipedia_search_rejects_invalid_query_without_network(
    monkeypatch: pytest.MonkeyPatch,
    query: object,
) -> None:
    def unexpected_network_call(redirect_handler):
        pytest.fail("Invalid query must not make a network request.")

    monkeypatch.setattr("agentforge.tools.safe_tools.build_opener", unexpected_network_call)

    with pytest.raises(ValueError, match="query must contain"):
        wikipedia_search_handler({"query": query})


def test_wikipedia_search_preserves_wrapped_network_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TimedOutOpener:
        def open(self, request, *, timeout):
            raise URLError(SocketTimeout("private timeout detail"))

    def timed_out(redirect_handler):
        return TimedOutOpener()

    monkeypatch.setattr("agentforge.tools.safe_tools.build_opener", timed_out)

    with pytest.raises(TimeoutError, match="Wikipedia search timed out"):
        wikipedia_search_handler({"query": "agent safety"})


def test_wikipedia_tool_is_not_called_until_explicit_workflow_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_body = json.dumps({"query": {"pages": {}}}).encode()

    requests, _ = install_fake_wikipedia_opener(
        monkeypatch,
        response_body=response_body,
    )
    engine = WorkflowEngine()
    pending = engine.create_execution(
        {
            "tasks": [
                {
                    "task_id": "search",
                    "agent_type": "researcher",
                    "tool_request": {
                        "tool_id": "wikipedia_search",
                        "arguments": {"query": "agent safety"},
                    },
                }
            ]
        }
    )

    assert requests == []
    result = engine.run(pending.execution_id)

    assert result.task_results["search"].tool_result is not None
    assert result.task_results["search"].tool_result.status == ToolExecutionStatus.SUCCEEDED
    assert len(requests) == 1


def test_wikipedia_search_bounds_encoded_output_with_unicode_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response_body = json.dumps(
        {
            "query": {
                "pages": {
                    str(page_id): {
                        "pageid": page_id,
                        "title": "\U0001f600" * 200,
                        "extract": "\U0001f600" * 400,
                    }
                    for page_id in range(1, 6)
                }
            }
        }
    ).encode()

    install_fake_wikipedia_opener(monkeypatch, response_body=response_body)

    result = wikipedia_search_handler({"query": "\U0001f600" * 200})
    encoded = json.dumps(result, ensure_ascii=True, separators=(",", ":")).encode()

    assert len(result["results"]) <= 5
    assert len(encoded) <= 5_000
