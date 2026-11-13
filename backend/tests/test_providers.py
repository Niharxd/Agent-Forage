import json
from io import BytesIO
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError

import pytest
from agentforge.agents.openai_planner import OpenAIPlannerAgent
from agentforge.config.settings import Settings
from agentforge.domain.agents.contracts import AgentErrorCode, AgentExecutionStatus
from agentforge.domain.workflows.models import WorkflowStatus
from agentforge.providers.contracts import ProviderError
from agentforge.providers.openai import OpenAIChatCompletionsProvider
from agentforge.workflow.engine import WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrationError, WorkflowOrchestrator
from pydantic import SecretStr

API_KEY = "test-key-not-for-logs"
ACCESS_TOKEN = "test-api-access-token"
VALID_PLAN = {
    "objective": "Inspect the supplied task.",
    "proposed_steps": [
        {
            "step_id": "draft-1",
            "assigned_role": "analyst",
            "instruction": "Inspect supplied information.",
        }
    ],
    "plan_status": "draft_only",
}


def make_provider() -> OpenAIChatCompletionsProvider:
    return OpenAIChatCompletionsProvider(
        api_key=SecretStr(API_KEY),
        model="gpt-4o-mini",
        timeout_seconds=5,
    )


def test_openai_provider_sends_bounded_structured_completion_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(VALID_PLAN)}}]}
    ).encode()

    def fake_urlopen(request, *, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return BytesIO(response_body)

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fake_urlopen)

    result = make_provider().generate_json(
        system_prompt="Return a JSON object.",
        user_prompt="Plan this task.",
    )

    request = captured["request"]
    assert request.full_url == "https://api.openai.com/v1/chat/completions"
    assert request.get_method() == "POST"
    assert request.get_header("Authorization") == f"Bearer {API_KEY}"
    assert captured["timeout"] == 5
    body = json.loads(request.data)
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_completion_tokens"] == 1200
    assert body["messages"][1]["content"] == "Plan this task."
    assert result == VALID_PLAN


def test_openai_provider_sanitizes_http_errors_and_keeps_key_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_with_http_error(request, *, timeout):
        raise HTTPError(request.full_url, 401, "private response", {}, BytesIO(API_KEY.encode()))

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fail_with_http_error)
    provider = make_provider()

    with pytest.raises(ProviderError) as raised:
        provider.generate_json(system_prompt="Plan.", user_prompt="Task.")

    assert raised.value.error.code == AgentErrorCode.EXECUTION_FAILURE
    assert raised.value.error.message == "The OpenAI provider rejected the request."
    assert API_KEY not in str(raised.value)
    assert API_KEY not in repr(provider)


def test_openai_provider_classifies_rate_limits_and_wrapped_timeouts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def rate_limited(request, *, timeout):
        raise HTTPError(request.full_url, 429, "private response", {}, BytesIO(b""))

    monkeypatch.setattr("agentforge.providers.openai.urlopen", rate_limited)
    with pytest.raises(ProviderError) as rate_limit_error:
        make_provider().generate_json(system_prompt="Plan.", user_prompt="Task.")
    assert rate_limit_error.value.error.retryable is True
    assert "rate limit" in rate_limit_error.value.error.message

    def timed_out(request, *, timeout):
        raise URLError(SocketTimeout("private timeout detail"))

    monkeypatch.setattr("agentforge.providers.openai.urlopen", timed_out)
    with pytest.raises(ProviderError) as timeout_error:
        make_provider().generate_json(system_prompt="Plan.", user_prompt="Task.")
    assert timeout_error.value.error.code == AgentErrorCode.TIMEOUT
    assert timeout_error.value.error.retryable is True
    assert "private timeout detail" not in str(timeout_error.value)


def test_openai_agent_sends_only_task_description_and_validates_draft() -> None:
    class FakeProvider:
        def __init__(self) -> None:
            self.user_prompt = ""

        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
            self.user_prompt = user_prompt
            return VALID_PLAN

    provider = FakeProvider()
    result = OpenAIPlannerAgent(provider).execute(
        {
            "task_description": "Create a short draft.",
            "input_data": {"private_value": "not sent"},
        }
    )

    assert provider.user_prompt == "Create a short draft."
    assert result.status == AgentExecutionStatus.SUCCEEDED
    assert result.metadata["execution_mode"] == "openai"
    assert result.output.metadata == {"planning_mode": "openai", "executable": False}


def test_openai_agent_rejects_invalid_plan_without_returning_provider_content() -> None:
    class InvalidProvider:
        def generate_json(self, *, system_prompt: str, user_prompt: str) -> dict[str, object]:
            return {"secret_response": "provider-internal"}

    result = OpenAIPlannerAgent(InvalidProvider()).execute({"task_description": "Create a draft."})

    assert result.status == AgentExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == AgentErrorCode.VALIDATION_FAILURE
    assert "provider-internal" not in result.model_dump_json()


def test_openai_mode_requires_an_environment_supplied_key() -> None:
    with pytest.raises(ValueError, match="OPENAI_API_KEY is required"):
        Settings(_env_file=None, provider_mode="openai")

    with pytest.raises(ValueError, match="API_ACCESS_TOKEN is required"):
        Settings(
            _env_file=None,
            provider_mode="openai",
            openai_api_key=SecretStr(API_KEY),
        )

    settings = Settings(
        _env_file=None,
        provider_mode="openai",
        openai_api_key=SecretStr(API_KEY),
        api_access_token=SecretStr(ACCESS_TOKEN),
    )
    assert API_KEY not in repr(settings)
    assert ACCESS_TOKEN not in repr(settings)


def test_engine_uses_openai_planner_only_after_explicit_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_headers: list[str | None] = []
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(VALID_PLAN)}}]}
    ).encode()

    def fake_urlopen(request, *, timeout):
        authorization_headers.append(request.get_header("Authorization"))
        return BytesIO(response_body)

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fake_urlopen)
    engine = WorkflowEngine(
        settings=Settings(
            _env_file=None,
            provider_mode="openai",
            openai_api_key=SecretStr(API_KEY),
            api_access_token=SecretStr(ACCESS_TOKEN),
        )
    )
    pending = engine.create_execution(
        {"tasks": [{"task_id": "plan", "agent_type": "planner", "description": "Create a draft."}]}
    )

    assert pending.status == WorkflowStatus.PENDING
    assert authorization_headers == []

    completed = engine.run(pending.execution_id)

    assert completed.status == WorkflowStatus.COMPLETED
    assert authorization_headers == [f"Bearer {API_KEY}"]
    assert API_KEY not in completed.model_dump_json()


def test_orchestrator_prepare_uses_engine_configured_openai_planner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authorization_headers: list[str | None] = []
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(VALID_PLAN)}}]}
    ).encode()

    def fake_urlopen(request, *, timeout):
        authorization_headers.append(request.get_header("Authorization"))
        return BytesIO(response_body)

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fake_urlopen)
    engine = WorkflowEngine(
        settings=Settings(
            _env_file=None,
            provider_mode="openai",
            openai_api_key=SecretStr(API_KEY),
            api_access_token=SecretStr(ACCESS_TOKEN),
        )
    )

    prepared = WorkflowOrchestrator(engine=engine).prepare("Inspect the supplied task.")

    assert prepared.planner_result.metadata["execution_mode"] == "openai"
    assert prepared.planner_result.output.metadata["planning_mode"] == "openai"
    assert prepared.execution.status == WorkflowStatus.PENDING
    assert authorization_headers == [f"Bearer {API_KEY}"]
    assert API_KEY not in prepared.model_dump_json()


def test_orchestrator_handles_provider_failure_without_leaking_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_with_provider_error(request, *, timeout):
        raise URLError("private provider response")

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fail_with_provider_error)
    engine = WorkflowEngine(
        settings=Settings(
            _env_file=None,
            provider_mode="openai",
            openai_api_key=SecretStr(API_KEY),
            api_access_token=SecretStr(ACCESS_TOKEN),
        )
    )

    with pytest.raises(WorkflowOrchestrationError) as raised:
        WorkflowOrchestrator(engine=engine).prepare("Inspect the supplied task.")

    assert raised.value.code == "planning_failed"
    assert "private provider response" not in str(raised.value)
    assert API_KEY not in str(raised.value)


def test_prepare_api_uses_configured_openai_planner_without_exposing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from uuid import uuid4

    from agentforge.api.dependencies import get_workflow_engine
    from agentforge.api.routes import workflows as workflow_routes
    from agentforge.api.schemas import WorkflowResponse
    from agentforge.database.dependencies import get_db_session
    from agentforge.main import create_app
    from fastapi.testclient import TestClient

    settings = Settings(
        _env_file=None,
        app_env="test",
        provider_mode="openai",
        openai_api_key=SecretStr(API_KEY),
        api_access_token=SecretStr(ACCESS_TOKEN),
    )
    application = create_app(settings)
    engine = WorkflowEngine(settings=settings)
    response_body = json.dumps(
        {"choices": [{"message": {"content": json.dumps(VALID_PLAN)}}]}
    ).encode()
    requests: list[tuple[str | None, str]] = []

    def fake_urlopen(request, *, timeout):
        requests.append((request.get_header("Authorization"), request.data.decode("utf-8")))
        return BytesIO(response_body)

    def override_session():
        yield None

    def persist_workflow(_session, definition, _snapshot, **_values):
        now = datetime.now(UTC)
        return WorkflowResponse(
            id=uuid4(),
            name=definition.name,
            description=definition.description,
            version=1,
            workflow_definition=definition,
            created_at=now,
            updated_at=now,
        )

    monkeypatch.setattr("agentforge.providers.openai.urlopen", fake_urlopen)
    monkeypatch.setattr(
        workflow_routes,
        "create_planned_workflow_execution",
        persist_workflow,
    )
    application.dependency_overrides[get_db_session] = override_session
    application.dependency_overrides[get_workflow_engine] = lambda: engine

    with TestClient(application) as client:
        response = client.post(
            "/api/v1/workflows/prepare",
            json={"task_description": "Inspect the supplied task."},
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        )

    assert response.status_code == 201
    assert response.json()["execution"]["status"] == "pending"
    assert len(requests) == 1
    assert requests[0][0] == f"Bearer {API_KEY}"
    request_data = json.loads(requests[0][1])
    assert request_data["messages"][1]["content"] == "Inspect the supplied task."
    assert API_KEY not in requests[0][1]
    assert API_KEY not in response.text
    assert ACCESS_TOKEN not in response.text


def test_openai_mode_requires_api_bearer_token_for_workflow_routes() -> None:
    from agentforge.main import create_app
    from fastapi.testclient import TestClient

    application = create_app(
        Settings(
            _env_file=None,
            app_env="test",
            provider_mode="openai",
            openai_api_key=SecretStr(API_KEY),
            api_access_token=SecretStr(ACCESS_TOKEN),
        )
    )
    request_body = {
        "name": "protected workflow",
        "description": "Test protected validation.",
        "tasks": [{"task_id": "analyze", "agent_type": "analyst"}],
    }
    prepare_body = {"task_description": "Prepare a protected task."}

    with TestClient(application) as client:
        unauthorized = client.post("/api/v1/workflows/validate", json=request_body)
        unauthorized_prepare = client.post("/api/v1/workflows/prepare", json=prepare_body)
        unauthorized_execution = client.get("/api/v1/executions")
        invalid_token = client.post(
            "/api/v1/workflows/validate",
            json=request_body,
            headers={"Authorization": "Bearer wrong-token"},
        )
        invalid_prepare_token = client.post(
            "/api/v1/workflows/prepare",
            json=prepare_body,
            headers={"Authorization": "Bearer wrong-token"},
        )
        authorized = client.post(
            "/api/v1/workflows/validate",
            json=request_body,
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
        )
        health = client.get("/api/v1/health")

    assert unauthorized.status_code == 401
    assert unauthorized_prepare.status_code == 401
    assert unauthorized_execution.status_code == 401
    assert invalid_token.status_code == 401
    assert invalid_prepare_token.status_code == 401
    assert authorized.status_code == 200
    assert authorized.json()["valid"] is True
    assert health.status_code == 200
    assert ACCESS_TOKEN not in (
        unauthorized.text
        + unauthorized_prepare.text
        + invalid_token.text
        + invalid_prepare_token.text
        + authorized.text
    )
