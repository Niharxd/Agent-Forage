from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from agentforge.agents import AnalystAgent, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentforge.api.dependencies import get_workflow_engine
from agentforge.api.routes import executions as execution_routes
from agentforge.api.routes import workflows as workflow_routes
from agentforge.api.schemas import WorkflowResponse
from agentforge.config.settings import Settings
from agentforge.database.dependencies import get_db_session
from agentforge.domain.agents import AgentRole
from agentforge.domain.workflows.models import (
    WorkflowDefinition,
    WorkflowExecutionSnapshot,
    WorkflowStatus,
)
from agentforge.main import create_app
from agentforge.workflow import ExecutionNotFoundError, WorkflowEngine
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, WorkflowEngine, FastAPI]:
    settings = Settings(_env_file=None, app_env="test")
    application = create_app(settings)
    workflow_engine = WorkflowEngine(settings=settings)
    stored_workflows: dict[UUID, WorkflowResponse] = {}
    stored_executions: dict[UUID, WorkflowExecutionSnapshot] = {}

    class FakeExecutionRepository:
        def __init__(self, _session) -> None:
            pass

        def create_execution(self, snapshot, **_values) -> None:
            stored_executions[snapshot.execution_id] = snapshot.model_copy(deep=True)

        def synchronize_execution(self, snapshot) -> None:
            stored_executions[snapshot.execution_id] = snapshot.model_copy(deep=True)

        def get_execution(self, execution_id: UUID) -> WorkflowExecutionSnapshot:
            snapshot = stored_executions.get(execution_id)
            if snapshot is None:
                raise ExecutionNotFoundError
            return snapshot.model_copy(deep=True)

        def list_executions(
            self,
            *,
            limit: int,
            offset: int,
            status: WorkflowStatus | None = None,
            search: str | None = None,
        ):
            records = sorted(
                stored_executions.values(),
                key=lambda item: (item.created_at, str(item.execution_id)),
                reverse=True,
            )
            if status is not None:
                records = [item for item in records if item.status == status]
            if search and search.strip():
                query = search.strip().casefold()
                records = [
                    item
                    for item in records
                    if query in str(item.execution_id).casefold()
                    or query in item.workflow_name.casefold()
                ]
            return [item.model_copy(deep=True) for item in records[offset : offset + limit]], len(
                records
            )

    def create_stored_workflow(_, definition: WorkflowDefinition) -> WorkflowResponse:
        versions = [
            item.version for item in stored_workflows.values() if item.name == definition.name
        ]
        now = datetime.now(UTC)
        record = WorkflowResponse(
            id=uuid4(),
            name=definition.name,
            description=definition.description,
            version=max(versions, default=0) + 1,
            workflow_definition=definition,
            created_at=now,
            updated_at=now,
        )
        stored_workflows[record.id] = record
        return record

    def get_stored_workflow(_, workflow_id: UUID) -> WorkflowResponse | None:
        return stored_workflows.get(workflow_id)

    def list_stored_workflows(_, *, limit: int, offset: int):
        records = sorted(
            stored_workflows.values(),
            key=lambda item: (item.name, -item.version),
        )
        return records[offset : offset + limit], len(records)

    def override_session():
        yield None

    monkeypatch.setattr(workflow_routes, "create_workflow", create_stored_workflow)
    monkeypatch.setattr(workflow_routes, "get_workflow", get_stored_workflow)
    monkeypatch.setattr(workflow_routes, "list_workflows", list_stored_workflows)
    monkeypatch.setattr(execution_routes, "get_workflow", get_stored_workflow)
    monkeypatch.setattr(execution_routes, "ExecutionRepository", FakeExecutionRepository)
    application.dependency_overrides[get_db_session] = override_session
    application.dependency_overrides[get_workflow_engine] = lambda: workflow_engine
    with TestClient(application, raise_server_exceptions=False) as client:
        yield client, workflow_engine, application


def workflow_body(name: str | None = None) -> dict[str, object]:
    return {
        "name": name or f"api-workflow-{uuid4().hex}",
        "description": "Workflow API test.",
        "tasks": [
            {
                "task_id": "analyze",
                "agent_type": "analyst",
                "input_data": {"labels": ["alpha", "beta"]},
            }
        ],
    }


def test_workflow_create_version_list_retrieve_and_validate(api) -> None:
    client, _, _ = api
    payload = workflow_body()

    created = client.post("/api/v1/workflows", json=payload)
    assert created.status_code == 201
    workflow = created.json()
    assert workflow["version"] == 1
    assert workflow["workflow_definition"]["tasks"][0]["task_id"] == "analyze"

    second_version = client.post("/api/v1/workflows", json=payload)
    assert second_version.status_code == 201
    assert second_version.json()["version"] == 2
    assert second_version.json()["id"] != workflow["id"]

    validated = client.post("/api/v1/workflows/validate", json=payload)
    assert validated.status_code == 200
    assert validated.json()["valid"] is True
    assert validated.json()["issues"] == []

    retrieved = client.get(f"/api/v1/workflows/{workflow['id']}")
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == workflow["id"]

    listing = client.get("/api/v1/workflows", params={"limit": 100})
    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert {item["id"] for item in listing.json()["items"]} >= {
        workflow["id"],
        second_version.json()["id"],
    }


def test_invalid_workflow_validation_and_creation_are_safe(api) -> None:
    client, _, _ = api
    payload = workflow_body()
    payload["tasks"] = [
        {
            "task_id": "secret-client-task",
            "agent_type": "analyst",
            "dependency_ids": ["unknown-secret-dependency"],
        }
    ]

    validation = client.post("/api/v1/workflows/validate", json=payload)
    assert validation.status_code == 200
    assert validation.json()["valid"] is False
    assert validation.json()["issues"][0]["code"] == "missing_dependency"
    assert "unknown-secret-dependency" not in validation.text

    creation = client.post("/api/v1/workflows", json=payload)
    assert creation.status_code == 422
    assert creation.json()["error"]["code"] == "workflow_validation_error"
    assert "secret-client-task" not in creation.text


def test_missing_workflow_and_invalid_payload_use_safe_http_errors(api) -> None:
    client, _, _ = api
    missing = client.get(f"/api/v1/workflows/{uuid4()}")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    missing_execution_workflow = client.post(f"/api/v1/workflows/{uuid4()}/executions")
    assert missing_execution_workflow.status_code == 404
    missing_execution = client.get(f"/api/v1/executions/{uuid4()}")
    assert missing_execution.status_code == 404

    invalid_payload = workflow_body()
    invalid_payload["tasks"] = [{"task_id": "bad", "agent_type": "not-an-agent"}]
    invalid = client.post("/api/v1/workflows", json=invalid_payload)
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"
    assert "not-an-agent" not in invalid.text


def test_execution_create_start_get_list_and_task_results(api) -> None:
    client, _, application = api
    workflow = client.post("/api/v1/workflows", json=workflow_body()).json()

    pending = client.post(f"/api/v1/workflows/{workflow['id']}/executions")
    assert pending.status_code == 201
    execution_id = pending.json()["execution_id"]
    assert pending.json()["status"] == "pending"
    assert pending.json()["task_results"]["analyze"]["status"] == "pending"

    started = client.post(f"/api/v1/executions/{execution_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "completed"
    assert started.json()["task_results"]["analyze"]["status"] == "completed"
    assert started.json()["execution_order"] == ["analyze"]

    retrieved = client.get(f"/api/v1/executions/{execution_id}")
    assert retrieved.status_code == 200
    assert retrieved.json()["status"] == "completed"

    listing = client.get("/api/v1/executions")
    assert listing.status_code == 200
    assert any(item["execution_id"] == execution_id for item in listing.json()["items"])

    repeated_start = client.post(f"/api/v1/executions/{execution_id}/start")
    assert repeated_start.status_code == 409
    assert repeated_start.json()["error"]["code"] == "conflict"

    application.state.workflow_engine = WorkflowEngine()
    retrieved_after_engine_replacement = client.get(f"/api/v1/executions/{execution_id}")
    assert retrieved_after_engine_replacement.status_code == 200
    assert retrieved_after_engine_replacement.json()["status"] == "completed"


def test_execution_list_filters_are_validated_and_applied(api) -> None:
    client, _, _ = api
    completed_workflow = client.post(
        "/api/v1/workflows",
        json=workflow_body("completed-search-target"),
    ).json()
    completed = client.post(f"/api/v1/workflows/{completed_workflow['id']}/executions").json()
    client.post(f"/api/v1/executions/{completed['execution_id']}/start")

    pending_workflow = client.post(
        "/api/v1/workflows",
        json=workflow_body("pending-search-target"),
    ).json()
    pending = client.post(f"/api/v1/workflows/{pending_workflow['id']}/executions").json()

    filtered = client.get(
        "/api/v1/executions",
        params={"status": "completed", "search": "COMPLETED-SEARCH"},
    )
    assert filtered.status_code == 200
    assert filtered.json()["total"] == 1
    assert filtered.json()["items"][0]["execution_id"] == completed["execution_id"]

    pending_results = client.get("/api/v1/executions", params={"status": "pending"})
    assert pending_results.status_code == 200
    assert [item["execution_id"] for item in pending_results.json()["items"]] == [
        pending["execution_id"]
    ]

    assert client.get("/api/v1/executions", params={"status": "unknown"}).status_code == 422
    assert client.get("/api/v1/executions", params={"search": "x" * 201}).status_code == 422


def test_pending_execution_can_be_cancelled_and_terminal_transitions_rejected(api) -> None:
    client, _, _ = api
    workflow = client.post("/api/v1/workflows", json=workflow_body()).json()
    pending = client.post(f"/api/v1/workflows/{workflow['id']}/executions").json()
    execution_id = pending["execution_id"]

    cancelled = client.post(f"/api/v1/executions/{execution_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert cancelled.json()["task_results"]["analyze"]["status"] == "skipped"

    invalid_cancel = client.post(f"/api/v1/executions/{execution_id}/cancel")
    assert invalid_cancel.status_code == 409


def test_persistence_failure_never_returns_execution_success(api, monkeypatch) -> None:
    client, _, _ = api
    workflow = client.post("/api/v1/workflows", json=workflow_body()).json()
    pending = client.post(f"/api/v1/workflows/{workflow['id']}/executions").json()

    def fail_synchronization(self, _snapshot) -> None:
        raise RuntimeError("private persistence details")

    monkeypatch.setattr(
        execution_routes.ExecutionRepository,
        "synchronize_execution",
        fail_synchronization,
    )
    response = client.post(f"/api/v1/executions/{pending['execution_id']}/start")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private persistence details" not in response.text


def test_running_execution_cancellation_is_cooperative_through_api(api) -> None:
    client, _, application = api
    entered = Event()
    release = Event()

    class BlockingAnalyst(AnalystAgent):
        def execute(self, value):
            entered.set()
            if not release.wait(timeout=5):
                raise TimeoutError("test release was not signalled")
            return super().execute(value)

    engine = WorkflowEngine(
        agents={
            AgentRole.PLANNER: PlannerAgent(),
            AgentRole.RESEARCHER: ResearcherAgent(),
            AgentRole.ANALYST: BlockingAnalyst(),
            AgentRole.REVIEWER: ReviewerAgent(),
        }
    )
    application.dependency_overrides[get_workflow_engine] = lambda: engine
    workflow = client.post("/api/v1/workflows", json=workflow_body()).json()
    pending = client.post(f"/api/v1/workflows/{workflow['id']}/executions").json()
    execution_id = pending["execution_id"]
    start_responses: list[object] = []
    start_thread = Thread(
        target=lambda: start_responses.append(
            client.post(f"/api/v1/executions/{execution_id}/start")
        )
    )
    start_thread.start()
    try:
        assert entered.wait(timeout=2)
        cancellation = client.post(f"/api/v1/executions/{execution_id}/cancel")
        assert cancellation.status_code == 200
        assert cancellation.json()["status"] == "running"
        assert cancellation.json()["cancellation_requested"] is True
    finally:
        release.set()
        start_thread.join(timeout=5)

    assert not start_thread.is_alive()
    assert len(start_responses) == 1
    assert start_responses[0].status_code == 200
    assert start_responses[0].json()["status"] == "cancelled"


def test_tool_permissions_are_enforced_before_workflow_creation(api) -> None:
    client, _, _ = api
    payload = {
        "name": f"unauthorized-tool-{uuid4().hex}",
        "tasks": [
            {
                "task_id": "unauthorized",
                "agent_type": "researcher",
                "tool_request": {
                    "tool_id": "calculator",
                    "arguments": {
                        "operation": "add",
                        "left": 1,
                        "right": 1,
                    },
                },
            }
        ],
    }

    response = client.post("/api/v1/workflows", json=payload)

    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["code"] == "unsafe_tool_request"


def test_api_rejects_oversized_request_body(api) -> None:
    client, _, _ = api
    response = client.post(
        "/api/v1/workflows/validate",
        content=b"x" * (1_048_577),
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "request_too_large"


def test_api_hides_unhandled_engine_exception(api) -> None:
    client, _, application = api
    workflow = client.post("/api/v1/workflows", json=workflow_body()).json()
    pending = client.post(f"/api/v1/workflows/{workflow['id']}/executions").json()

    class BrokenEngine:
        def run(self, execution_id):
            raise RuntimeError("private exception details")

    application.dependency_overrides[get_workflow_engine] = lambda: BrokenEngine()
    response = client.post(f"/api/v1/executions/{pending['execution_id']}/start")

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert "private exception details" not in response.text
