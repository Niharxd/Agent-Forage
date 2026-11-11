import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from agentforge.api.services.executions import (
    ExecutionAlreadyExistsError,
    ExecutionPersistenceError,
    ExecutionRepository,
)
from agentforge.config.settings import Settings
from agentforge.database.dependencies import get_db_session
from agentforge.database.engine import create_database_engine
from agentforge.domain.models import (
    ApprovalRequest,
    Base,
    ExecutionEvent,
    ExecutionStep,
    ToolExecutionRecord,
    User,
    Workflow,
    WorkflowExecution,
)
from agentforge.domain.workflows.models import (
    TaskStatus,
    WorkflowDefinition,
    WorkflowEventType,
    WorkflowExecutionSnapshot,
    WorkflowStatus,
)
from agentforge.main import create_app
from agentforge.workflow import ExecutionNotFoundError, WorkflowEngine
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME = "agentforge_test"


def _alembic_config(connection: object | None = None) -> Config:
    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    if connection is not None:
        config.attributes["connection"] = connection
    return config


@pytest.fixture(scope="session")
def migrated_database() -> Iterator[Engine]:
    settings = Settings()
    database_url = os.environ.get("TEST_DATABASE_URL", settings.test_database_url)
    test_url = make_url(database_url)
    application_url = make_url(settings.database_url)
    if (
        test_url.database != TEST_DATABASE_NAME
        or test_url.host not in {None, "localhost", "127.0.0.1", "::1"}
        or test_url == application_url
    ):
        pytest.fail(
            "Database integration tests require a local TEST_DATABASE_URL "
            f"whose database is named {TEST_DATABASE_NAME!r} and differs from DATABASE_URL."
        )

    engine = create_database_engine(database_url)
    try:
        with engine.begin() as connection:
            Base.metadata.drop_all(connection)
            connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
            connection.execute(
                text("DROP FUNCTION IF EXISTS public.prevent_execution_event_mutation()")
            )

        with engine.connect() as connection:
            command.upgrade(_alembic_config(connection), "head")

        yield engine
    finally:
        try:
            with engine.begin() as connection:
                Base.metadata.drop_all(connection)
                connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
                connection.execute(
                    text("DROP FUNCTION IF EXISTS public.prevent_execution_event_mutation()")
                )
        finally:
            engine.dispose()


@pytest.fixture
def db_session(migrated_database: Engine) -> Iterator[Session]:
    with Session(migrated_database) as session:
        yield session
        session.rollback()


def test_settings_select_test_database_and_reject_non_postgresql_urls() -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql+psycopg://localhost/agentforge",
        test_database_url="postgresql+psycopg://localhost/agentforge_test",
    )

    assert settings.runtime_database_url == settings.test_database_url
    with pytest.raises(ValueError):
        Settings(_env_file=None, database_url="sqlite:///local.db")


def test_settings_load_database_urls_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    application_url = "postgresql+psycopg://localhost/agentforge"
    test_url = "postgresql+psycopg://localhost/agentforge_test"
    monkeypatch.setenv("DATABASE_URL", application_url)
    monkeypatch.setenv("TEST_DATABASE_URL", test_url)
    monkeypatch.setenv("APP_ENV", "test")

    settings = Settings(_env_file=None)

    assert settings.database_url == application_url
    assert settings.test_database_url == test_url
    assert settings.runtime_database_url == test_url


def test_model_relationships_persist_and_timestamp_fields_are_populated(
    db_session: Session,
) -> None:
    workflow = Workflow(
        name="research",
        workflow_definition={"schema_version": 1, "steps": []},
        version=1,
    )
    execution = WorkflowExecution(
        original_task="Research a topic",
        status="submitted",
        workflow=workflow,
    )
    step = ExecutionStep(
        task_id="research-1",
        agent_type="researcher",
        status="pending",
        execution=execution,
    )
    approval = ApprovalRequest(
        execution=execution,
        execution_step=step,
        action_description="Send a report",
        action_digest="a" * 64,
        safe_arguments={"recipient": "redacted@example.invalid"},
        status="pending",
    )
    tool_record = ToolExecutionRecord(
        execution=execution,
        execution_step=step,
        tool_name="report_sender",
        status="requested",
    )
    event = ExecutionEvent(
        execution=execution,
        event_type="execution_submitted",
        to_status="submitted",
    )
    db_session.add(execution)
    db_session.flush()

    assert execution.id is not None
    assert step.execution is execution
    assert approval.execution is execution
    assert tool_record.execution_step is step
    assert event.execution is execution
    assert workflow.created_at is not None
    assert workflow.updated_at is not None
    assert execution.created_at is not None
    assert db_session.scalar(select(Workflow).where(Workflow.id == workflow.id)) is workflow


def test_user_email_and_workflow_version_are_unique(db_session: Session) -> None:
    db_session.add(User(email="operator@example.invalid"))
    db_session.flush()

    db_session.add(User(email="operator@example.invalid"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    db_session.add(Workflow(name="unique-workflow", workflow_definition={}, version=1))
    db_session.flush()
    db_session.add(Workflow(name="unique-workflow", workflow_definition={}, version=1))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_invalid_execution_reference_is_rejected_by_foreign_key(
    db_session: Session,
) -> None:
    db_session.add(
        ExecutionStep(
            execution_id=uuid4(),
            task_id="orphaned-step",
            agent_type="analyst",
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_transaction_rollback_removes_uncommitted_record(
    db_session: Session,
    migrated_database: Engine,
) -> None:
    user = User(email="rollback@example.invalid")
    db_session.add(user)
    db_session.flush()
    user_id = user.id
    db_session.rollback()

    with Session(migrated_database) as verification_session:
        assert verification_session.get(User, user_id) is None


def test_execution_events_cannot_be_updated_or_deleted(db_session: Session) -> None:
    event = ExecutionEvent(
        execution=WorkflowExecution(original_task="Audit this", status="submitted"),
        event_type="execution_submitted",
        to_status="submitted",
    )
    db_session.add(event)
    db_session.flush()
    event_id = event.id
    db_session.commit()

    with pytest.raises(DBAPIError):
        db_session.execute(
            update(ExecutionEvent).where(ExecutionEvent.id == event_id).values(reason="modified")
        )
    db_session.rollback()

    with pytest.raises(DBAPIError):
        db_session.execute(delete(ExecutionEvent).where(ExecutionEvent.id == event_id))
    db_session.rollback()


def test_fastapi_session_dependency_closes_request_session(
    migrated_database: Engine,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        test_database_url=os.environ.get(
            "TEST_DATABASE_URL",
            Settings(_env_file=None).test_database_url,
        ),
    )
    application = create_app(settings)
    observed_sessions: list[Session] = []

    @application.get("/database-check")
    def database_check(session: Session = Depends(get_db_session)) -> dict[str, int]:
        observed_sessions.append(session)
        return {"result": session.scalar(text("SELECT 1"))}

    with TestClient(application) as client:
        response = client.get("/database-check")
        engine = application.state.engine
        assert engine.pool.checkedout() == 0

    assert response.status_code == 200
    assert response.json() == {"result": 1}
    assert len(observed_sessions) == 1
    assert observed_sessions[0].get_transaction() is None
    assert engine.pool.checkedout() == 0


def test_workflow_api_persists_versioned_definitions(migrated_database: Engine) -> None:
    settings = Settings(app_env="test")
    application = create_app(settings)
    workflow_name = f"api-persistence-{uuid4().hex}"
    payload = {
        "name": workflow_name,
        "description": "Persisted by the workflow API.",
        "tasks": [{"task_id": "analyze", "agent_type": "analyst"}],
    }

    with TestClient(application) as client:
        first = client.post("/api/v1/workflows", json=payload)
        second = client.post("/api/v1/workflows", json=payload)
        listed = client.get("/api/v1/workflows", params={"limit": 100})

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["version"] == 1
    assert second.json()["version"] == 2
    assert any(item["name"] == workflow_name for item in listed.json()["items"])
    with Session(migrated_database) as session:
        records = session.scalars(select(Workflow).where(Workflow.name == workflow_name)).all()
        assert sorted(record.version for record in records) == [1, 2]


def test_migration_metadata_matches_current_schema_and_supports_rollback(
    migrated_database: Engine,
) -> None:
    config = _alembic_config()
    assert ScriptDirectory.from_config(config).get_current_head() is not None

    with migrated_database.connect() as connection:
        command.check(_alembic_config(connection))
        current_revision = MigrationContext.configure(connection).get_current_revision()
    assert current_revision == ScriptDirectory.from_config(config).get_current_head()

    with migrated_database.connect() as connection:
        command.downgrade(_alembic_config(connection), "base")
        assert MigrationContext.configure(connection).get_current_revision() is None
        command.upgrade(_alembic_config(connection), "head")
        connection.commit()


def _create_persisted_execution(
    session: Session,
    *,
    definition: WorkflowDefinition,
    engine: WorkflowEngine | None = None,
) -> tuple[Workflow, WorkflowEngine, ExecutionRepository, WorkflowExecutionSnapshot]:
    workflow = Workflow(
        name=f"execution-test-{uuid4().hex}",
        description="A persisted workflow.",
        workflow_definition=definition.model_dump(mode="json"),
        version=1,
    )
    session.add(workflow)
    session.commit()
    workflow_engine = engine or WorkflowEngine()
    repository = ExecutionRepository(session)
    snapshot = workflow_engine.create_execution(
        definition,
        on_update=lambda value: repository.create_execution(
            value,
            workflow_id=workflow.id,
            workflow_version=workflow.version,
            definition=definition,
        ),
    )
    return workflow, workflow_engine, repository, snapshot


def _one_task_definition(*, dependent: bool = False) -> WorkflowDefinition:
    tasks = [{"task_id": "first", "agent_type": "analyst"}]
    if dependent:
        tasks.append(
            {
                "task_id": "blocked",
                "agent_type": "analyst",
                "dependency_ids": ["first"],
            }
        )
    return WorkflowDefinition(name="execution persistence", tasks=tasks)


def test_execution_create_persists_reference_tasks_and_ordered_created_event(
    db_session: Session,
) -> None:
    workflow, _, _, snapshot = _create_persisted_execution(
        db_session,
        definition=_one_task_definition(),
    )
    record = db_session.get(WorkflowExecution, snapshot.execution_id)
    steps = db_session.scalars(
        select(ExecutionStep).where(ExecutionStep.execution_id == snapshot.execution_id)
    ).all()
    events = db_session.scalars(
        select(ExecutionEvent)
        .where(ExecutionEvent.execution_id == snapshot.execution_id)
        .order_by(ExecutionEvent.sequence_number)
    ).all()

    assert record is not None
    assert record.workflow_id == workflow.id
    assert record.plan_version == workflow.version
    assert record.status == WorkflowStatus.PENDING.value
    assert record.created_at.tzinfo is not None
    assert record.started_at is None and record.completed_at is None
    assert len(steps) == 1
    assert steps[0].task_id == "first"
    assert steps[0].status == TaskStatus.PENDING.value
    assert steps[0].output_data["status"] == TaskStatus.PENDING.value
    assert [(event.sequence_number, event.event_type) for event in events] == [
        (1, WorkflowEventType.WORKFLOW_CREATED.value)
    ]


def test_completed_execution_reconstructs_results_timestamps_and_event_order(
    migrated_database: Engine,
) -> None:
    definition = _one_task_definition()
    with Session(migrated_database) as session:
        _, engine, repository, pending = _create_persisted_execution(
            session,
            definition=definition,
        )
        completed = engine.run(
            pending.execution_id,
            on_update=repository.synchronize_execution,
        )
        repository.synchronize_execution(completed.snapshot())

    with Session(migrated_database) as session:
        reconstructed = ExecutionRepository(session).get_execution(pending.execution_id)

    assert reconstructed.status == WorkflowStatus.COMPLETED
    assert reconstructed.started_at is not None and reconstructed.completed_at is not None
    assert reconstructed.task_results["first"].status == TaskStatus.COMPLETED
    assert reconstructed.task_results["first"].agent_result is not None
    assert reconstructed.task_results["first"].started_at is not None
    assert reconstructed.task_results["first"].completed_at is not None
    assert reconstructed.execution_order == ["first"]
    assert [event.event_type for event in reconstructed.events] == [
        WorkflowEventType.WORKFLOW_CREATED,
        WorkflowEventType.WORKFLOW_STARTED,
        WorkflowEventType.TASK_STARTED,
        WorkflowEventType.TASK_COMPLETED,
        WorkflowEventType.WORKFLOW_COMPLETED,
    ]
    assert [event.timestamp for event in reconstructed.events] == sorted(
        event.timestamp for event in reconstructed.events
    )

    with Session(migrated_database) as session:
        persisted_event_count = session.scalar(
            select(func.count())
            .select_from(ExecutionEvent)
            .where(ExecutionEvent.execution_id == pending.execution_id)
        )
    assert persisted_event_count == len(reconstructed.events)


def test_execution_list_filters_search_and_pagination_use_postgresql(
    migrated_database: Engine,
) -> None:
    with Session(migrated_database) as session:
        first_workflow, first_engine, first_repository, first_pending = _create_persisted_execution(
            session, definition=_one_task_definition()
        )
        first_workflow.name = "Dashboard Search Alpha"
        session.commit()
        first_engine.run(
            first_pending.execution_id,
            on_update=first_repository.synchronize_execution,
        )

        second_workflow, _, _, second_pending = _create_persisted_execution(
            session,
            definition=_one_task_definition(),
        )
        second_workflow.name = "Dashboard Search Beta"
        session.commit()

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        completed, completed_total = repository.list_executions(
            limit=10,
            offset=0,
            status=WorkflowStatus.COMPLETED,
            search="Dashboard Search",
        )
        by_workflow, workflow_total = repository.list_executions(
            limit=10,
            offset=0,
            search="dashboard search beta",
        )
        by_id, id_total = repository.list_executions(
            limit=10,
            offset=0,
            search=str(first_pending.execution_id)[:12],
        )
        all_records, all_total = repository.list_executions(
            limit=10,
            offset=0,
            search="Dashboard Search",
        )
        page, page_total = repository.list_executions(
            limit=1,
            offset=1,
            search="Dashboard Search",
        )

    assert completed_total == 1
    assert [execution.execution_id for execution in completed] == [first_pending.execution_id]
    assert workflow_total == 1
    assert [execution.execution_id for execution in by_workflow] == [second_pending.execution_id]
    assert id_total == 1
    assert [execution.execution_id for execution in by_id] == [first_pending.execution_id]
    assert all_total == 2
    assert page_total == 2
    assert len(page) == 1
    assert page[0].execution_id == all_records[1].execution_id


def test_execution_search_treats_like_wildcards_as_literals(migrated_database: Engine) -> None:
    prefix = f"literal-search-{uuid4().hex}-"
    workflow_names = [
        f"{prefix}percent%token",
        f"{prefix}percentXtoken",
        f"{prefix}under_score",
        f"{prefix}underXscore",
        f"{prefix}slash\\token",
        f"{prefix}slash/token",
    ]

    with Session(migrated_database) as session:
        expected_ids = {}
        for name in workflow_names:
            workflow, _, _, snapshot = _create_persisted_execution(
                session,
                definition=_one_task_definition(),
            )
            workflow.name = name
            expected_ids[name] = snapshot.execution_id
        session.commit()

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        searches = {
            f"{prefix}percent%token": expected_ids[workflow_names[0]],
            f"{prefix}under_score": expected_ids[workflow_names[2]],
            f"{prefix}slash\\token": expected_ids[workflow_names[4]],
        }
        for query, expected_id in searches.items():
            matches, total = repository.list_executions(
                limit=10,
                offset=0,
                search=query,
            )
            assert total == 1
            assert [execution.execution_id for execution in matches] == [expected_id]


def test_failed_and_blocked_task_states_reconstruct_from_database(
    migrated_database: Engine,
) -> None:
    definition = _one_task_definition(dependent=True)
    limited_engine = WorkflowEngine(
        settings=Settings(_env_file=None, workflow_max_task_input_bytes=2)
    )
    with Session(migrated_database) as session:
        _, engine, repository, pending = _create_persisted_execution(
            session,
            definition=definition,
            engine=limited_engine,
        )
        engine.run(pending.execution_id, on_update=repository.synchronize_execution)

    with Session(migrated_database) as session:
        reconstructed = ExecutionRepository(session).get_execution(pending.execution_id)

    assert reconstructed.status == WorkflowStatus.FAILED
    assert reconstructed.task_results["first"].status == TaskStatus.FAILED
    assert reconstructed.task_results["first"].error is not None
    assert reconstructed.task_results["blocked"].status == TaskStatus.BLOCKED
    assert reconstructed.task_results["blocked"].error is not None
    assert WorkflowEventType.TASK_FAILED in [event.event_type for event in reconstructed.events]
    assert WorkflowEventType.TASK_BLOCKED in [event.event_type for event in reconstructed.events]
    with Session(migrated_database) as session:
        failure_event = session.scalar(
            select(ExecutionEvent).where(
                ExecutionEvent.execution_id == pending.execution_id,
                ExecutionEvent.event_type == WorkflowEventType.TASK_FAILED.value,
            )
        )
    assert failure_event is not None
    assert "error" not in failure_event.details


def test_pending_cancellation_persists_skips_and_terminal_state(
    migrated_database: Engine,
) -> None:
    with Session(migrated_database) as session:
        _, engine, repository, pending = _create_persisted_execution(
            session,
            definition=_one_task_definition(dependent=True),
        )
        engine.cancel(pending.execution_id, on_update=repository.synchronize_execution)

    with Session(migrated_database) as session:
        reconstructed = ExecutionRepository(session).get_execution(pending.execution_id)

    assert reconstructed.status == WorkflowStatus.CANCELLED
    assert reconstructed.completed_at is not None
    assert all(
        result.status == TaskStatus.SKIPPED for result in reconstructed.task_results.values()
    )
    assert reconstructed.events[-1].event_type == WorkflowEventType.WORKFLOW_CANCELLED


def test_initial_execution_transaction_rolls_back_all_rows_on_commit_failure(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    definition = _one_task_definition()
    with Session(migrated_database) as session:
        workflow = Workflow(
            name=f"rollback-{uuid4().hex}",
            workflow_definition=definition.model_dump(mode="json"),
            version=1,
        )
        session.add(workflow)
        session.commit()
        execution_id = uuid4()
        snapshot = WorkflowEngine().create_execution(definition, execution_id=execution_id)
        repository = ExecutionRepository(session)

        def fail_commit() -> None:
            raise RuntimeError("controlled commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)
        with pytest.raises(ExecutionPersistenceError):
            repository.create_execution(
                snapshot,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                definition=definition,
            )

    with Session(migrated_database) as session:
        assert session.get(WorkflowExecution, execution_id) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionStep)
                .where(ExecutionStep.execution_id == execution_id)
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionEvent)
                .where(ExecutionEvent.execution_id == execution_id)
            )
            == 0
        )


def test_event_failure_does_not_report_durable_success_or_leave_partial_state(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(migrated_database) as session:
        _, engine, repository, pending = _create_persisted_execution(
            session,
            definition=_one_task_definition(),
        )
        insert_events = repository._insert_events

        def fail_on_task_completion(events, *, start_sequence: int = 1) -> None:
            if any(event.event_type == WorkflowEventType.TASK_COMPLETED for event in events):
                raise RuntimeError("controlled event insert failure")
            insert_events(events, start_sequence=start_sequence)

        monkeypatch.setattr(repository, "_insert_events", fail_on_task_completion)
        with pytest.raises(ExecutionPersistenceError):
            engine.run(pending.execution_id, on_update=repository.synchronize_execution)

    with Session(migrated_database) as session:
        durable = ExecutionRepository(session).get_execution(pending.execution_id)

    assert durable.status == WorkflowStatus.RUNNING
    assert durable.task_results["first"].status == TaskStatus.RUNNING
    assert WorkflowEventType.TASK_COMPLETED not in [event.event_type for event in durable.events]


def test_terminal_persistence_failure_does_not_report_durable_completion(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with Session(migrated_database) as session:
        _, engine, repository, pending = _create_persisted_execution(
            session,
            definition=_one_task_definition(),
        )
        insert_events = repository._insert_events

        def fail_on_workflow_completion(events, *, start_sequence: int = 1) -> None:
            if any(event.event_type == WorkflowEventType.WORKFLOW_COMPLETED for event in events):
                raise RuntimeError("controlled terminal event insert failure")
            insert_events(events, start_sequence=start_sequence)

        monkeypatch.setattr(repository, "_insert_events", fail_on_workflow_completion)
        with pytest.raises(ExecutionPersistenceError):
            engine.run(pending.execution_id, on_update=repository.synchronize_execution)

    with Session(migrated_database) as session:
        durable = ExecutionRepository(session).get_execution(pending.execution_id)

    assert durable.status == WorkflowStatus.RUNNING
    assert durable.task_results["first"].status == TaskStatus.COMPLETED
    assert durable.completed_at is None
    assert WorkflowEventType.WORKFLOW_COMPLETED not in [
        event.event_type for event in durable.events
    ]


def test_duplicate_execution_creation_is_rejected_without_duplicate_events(
    migrated_database: Engine,
) -> None:
    definition = _one_task_definition()
    with Session(migrated_database) as session:
        workflow, _, repository, snapshot = _create_persisted_execution(
            session,
            definition=definition,
        )
        with pytest.raises(ExecutionAlreadyExistsError):
            repository.create_execution(
                snapshot,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                definition=definition,
            )

    with Session(migrated_database) as session:
        reconstructed = ExecutionRepository(session).get_execution(snapshot.execution_id)

    assert len(reconstructed.events) == 1


def test_missing_persisted_execution_raises_not_found(
    migrated_database: Engine,
) -> None:
    with Session(migrated_database) as session:
        with pytest.raises(ExecutionNotFoundError):
            ExecutionRepository(session).get_execution(uuid4())


def test_persisted_execution_api_survives_engine_history_replacement(
    migrated_database: Engine,
) -> None:
    settings = Settings(_env_file=None, app_env="test")
    application = create_app(settings)
    payload = {
        "name": f"api-execution-{uuid4().hex}",
        "description": "Persisted API execution.",
        "tasks": [
            {
                "task_id": "gather",
                "agent_type": "analyst",
                "input_data": {"private_marker": "do-not-return"},
            },
            {
                "task_id": "analyze",
                "agent_type": "analyst",
                "dependency_ids": ["gather"],
            },
        ],
    }

    with TestClient(application) as client:
        workflow_response = client.post("/api/v1/workflows", json=payload)
        assert workflow_response.status_code == 201
        workflow_id = workflow_response.json()["id"]
        create_response = client.post(f"/api/v1/workflows/{workflow_id}/executions")
        assert create_response.status_code == 201
        execution_id = create_response.json()["execution_id"]
        start_response = client.post(f"/api/v1/executions/{execution_id}/start")
        assert start_response.status_code == 200
        assert start_response.json()["status"] == "completed"

        application.state.workflow_engine = WorkflowEngine(settings=settings)
        retrieved = client.get(f"/api/v1/executions/{execution_id}")
        listing = client.get("/api/v1/executions", params={"limit": 1})
        cancelled_create = client.post(f"/api/v1/workflows/{workflow_id}/executions")
        cancellation = client.post(
            f"/api/v1/executions/{cancelled_create.json()['execution_id']}/cancel"
        )

    assert retrieved.status_code == 200
    assert retrieved.json()["execution_id"] == execution_id
    assert retrieved.json()["events"][-1]["event_type"] == "workflow_completed"
    assert retrieved.json()["workflow_plan"] == [
        {
            "task_id": "gather",
            "agent_type": "analyst",
            "dependency_ids": [],
            "status": "completed",
        },
        {
            "task_id": "analyze",
            "agent_type": "analyst",
            "dependency_ids": ["gather"],
            "status": "completed",
        },
    ]
    assert "do-not-return" not in str(retrieved.json()["workflow_plan"])
    assert listing.status_code == 200
    assert listing.json()["total"] >= 2
    assert cancellation.status_code == 200
    assert cancellation.json()["status"] == "cancelled"
