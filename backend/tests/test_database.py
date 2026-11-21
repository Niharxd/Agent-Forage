import os
from collections.abc import Iterator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from agentforge.api.services.executions import (
    ExecutionAlreadyExistsError,
    ExecutionPersistenceError,
    ExecutionRepository,
)
from agentforge.api.services.workflows import create_planned_workflow_execution
from agentforge.config.settings import Settings
from agentforge.database.dependencies import get_db_session
from agentforge.database.engine import create_database_engine
from agentforge.domain.agents.contracts import AgentCapability, AgentRole
from agentforge.domain.models import (
    ApprovalRequest,
    Base,
    ExecutionEvent,
    ExecutionStep,
    ToolExecutionRecord,
    User,
    Workflow,
    WorkflowExecution,
    Workspace,
    WorkspaceMembership,
)
from agentforge.domain.workflows.models import (
    TaskStatus,
    WorkflowDefinition,
    WorkflowEventType,
    WorkflowExecutionSnapshot,
    WorkflowStatus,
    WorkflowTask,
    WorkflowToolRequest,
)
from agentforge.main import create_app
from agentforge.tools import (
    ToolDefinition,
    ToolExecutor,
    ToolRegistry,
)
from agentforge.workflow import ExecutionNotFoundError, WorkflowEngine
from agentforge.workflow.orchestrator import WorkflowOrchestrator
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

BACKEND_ROOT = Path(__file__).resolve().parents[1]
TEST_DATABASE_NAME = "agentforge_test"
TEST_DATABASE_URL = "postgresql+psycopg://agentforge@localhost/agentforge_test"


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


def _legacy_workspace(session: Session) -> Workspace:
    workspace = session.scalar(select(Workspace).where(Workspace.slug == "legacy-operator"))
    if workspace is None:
        raise AssertionError("The migration did not create the legacy workspace.")
    return workspace


def test_legacy_workspace_is_created_for_existing_operator_compatibility(
    db_session: Session,
) -> None:
    legacy = _legacy_workspace(db_session)
    owner = db_session.get(User, legacy.owner_id)

    assert owner is not None
    assert owner.account_status == "active"
    assert legacy.name == "Legacy Operator Workspace"
    membership = db_session.scalar(
        select(WorkspaceMembership).where(
            WorkspaceMembership.workspace_id == legacy.id,
            WorkspaceMembership.user_id == owner.id,
        )
    )
    assert membership is not None
    assert membership.role == "owner"


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
    legacy_workspace = _legacy_workspace(db_session)
    workflow = Workflow(
        name="research",
        workflow_definition={"schema_version": 1, "steps": []},
        version=1,
        workspace=legacy_workspace,
        created_by=legacy_workspace.owner,
        updated_by=legacy_workspace.owner,
    )
    execution = WorkflowExecution(
        original_task="Research a topic",
        status="submitted",
        workflow=workflow,
        workspace=legacy_workspace,
        created_by=legacy_workspace.owner,
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


def test_planner_created_workflow_and_pending_execution_persist_together(
    db_session: Session,
) -> None:
    workflow_name = f"planner-proposed-{uuid4().hex}"
    definition = WorkflowDefinition.model_validate(
        {
            "name": workflow_name,
            "description": "Inspect the supplied task.",
            "tasks": [
                {
                    "task_id": "draft-1",
                    "agent_type": "analyst",
                    "description": "Inspect supplied information.",
                }
            ],
        }
    )
    pending = WorkflowEngine().create_execution(definition)

    original_task = "x" * 10_000
    saved_workflow = create_planned_workflow_execution(
        db_session,
        definition,
        pending,
        original_task=original_task,
    )
    saved_execution, saved_definition = ExecutionRepository(db_session).get_execution_details(
        pending.execution_id
    )

    assert saved_workflow.version == 1
    assert saved_execution.status == WorkflowStatus.PENDING
    assert saved_execution.execution_order == []
    assert saved_definition == definition
    saved_execution_record = db_session.get(WorkflowExecution, pending.execution_id)
    assert saved_execution_record is not None
    assert saved_execution_record.original_task == original_task

    with pytest.raises(ExecutionAlreadyExistsError):
        create_planned_workflow_execution(
            db_session,
            definition,
            pending,
            original_task=original_task,
        )
    assert (
        db_session.scalar(
            select(func.count()).select_from(Workflow).where(Workflow.name == workflow_name)
        )
        == 1
    )


def test_planned_workflow_commit_failure_rolls_back_before_engine_registration(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_description = f"Commit-failure regression {uuid4().hex}"
    engine = WorkflowEngine()
    orchestrator = WorkflowOrchestrator(engine=engine)
    execution_ids = []

    with Session(migrated_database) as session:
        workflow_count_before = session.scalar(
            select(func.count())
            .select_from(Workflow)
            .where(Workflow.name == "planner-proposed workflow")
        )

        def fail_commit() -> None:
            raise RuntimeError("controlled commit failure")

        monkeypatch.setattr(session, "commit", fail_commit)

        def persist_prepared(definition, snapshot) -> None:
            execution_ids.append(snapshot.execution_id)
            create_planned_workflow_execution(
                session,
                definition,
                snapshot,
                original_task=task_description,
            )

        with pytest.raises(ExecutionPersistenceError):
            orchestrator.prepare(task_description, on_prepared=persist_prepared)

    assert len(execution_ids) == 1
    with pytest.raises(ExecutionNotFoundError):
        engine.get_execution(execution_ids[0])

    with Session(migrated_database) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(Workflow)
                .where(Workflow.name == "planner-proposed workflow")
            )
            == workflow_count_before
        )
        assert session.get(WorkflowExecution, execution_ids[0]) is None
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionStep)
                .where(ExecutionStep.execution_id == execution_ids[0])
            )
            == 0
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(ExecutionEvent)
                .where(ExecutionEvent.execution_id == execution_ids[0])
            )
            == 0
        )


def test_prepare_route_survives_postcommit_refresh_failure_and_registers_execution(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        _env_file=None,
        app_env="test",
        test_database_url=TEST_DATABASE_URL,
    )
    application = create_app(settings)
    original_commit = Session.commit
    original_refresh = Session.refresh

    def track_commit(session: Session) -> None:
        original_commit(session)
        session.info["committed_for_test"] = True

    def fail_postcommit_refresh(session: Session, instance: object, *args, **kwargs) -> None:
        if session.info.get("committed_for_test"):
            raise RuntimeError("simulated post-commit refresh failure")
        original_refresh(session, instance, *args, **kwargs)

    monkeypatch.setattr(Session, "commit", track_commit)
    monkeypatch.setattr(Session, "refresh", fail_postcommit_refresh)

    task_description = f"Integration route regression {uuid4().hex}"
    with TestClient(application, raise_server_exceptions=False) as client:
        prepared_response = client.post(
            "/api/v1/workflows/prepare",
            json={"task_description": task_description},
        )

        assert prepared_response.status_code == 201
        prepared = prepared_response.json()
        execution_id = UUID(prepared["execution"]["execution_id"])
        assert prepared["execution"]["status"] == WorkflowStatus.PENDING.value
        assert prepared["execution"]["execution_order"] == []

        pending_response = client.get(f"/api/v1/executions/{execution_id}")
        assert pending_response.status_code == 200
        assert pending_response.json()["status"] == WorkflowStatus.PENDING.value

        started_response = client.post(f"/api/v1/executions/{execution_id}/start")
        assert started_response.status_code == 200
        assert started_response.json()["status"] == WorkflowStatus.COMPLETED.value
        assert started_response.json()["execution_order"]

    with Session(migrated_database) as session:
        execution_record = session.get(WorkflowExecution, execution_id)
        assert execution_record is not None
        assert execution_record.original_task == task_description


def test_user_email_and_workflow_version_are_unique(db_session: Session) -> None:
    db_session.add(User(email="  OPERATOR@EXAMPLE.INVALID "))
    db_session.flush()
    user = db_session.scalar(select(User).where(User.email == "operator@example.invalid"))
    assert user is not None
    assert user.account_status == "pending"

    db_session.add(User(email="operator@example.invalid"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    legacy_workspace = _legacy_workspace(db_session)
    db_session.add(
        Workflow(
            name="unique-workflow",
            workflow_definition={},
            version=1,
            workspace=legacy_workspace,
        )
    )
    db_session.flush()
    db_session.add(
        Workflow(
            name="unique-workflow",
            workflow_definition={},
            version=1,
            workspace=legacy_workspace,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_workspace_membership_and_user_models(db_session: Session) -> None:
    owner = User(
        email="  Owner@Example.Invalid ",
        password_hash="not-a-plaintext-password",
        account_status="active",
    )
    db_session.add(owner)
    db_session.flush()

    assert owner.email == "owner@example.invalid"
    workspace = Workspace(name="Private Workspace", slug="private-workspace", owner=owner)
    db_session.add(workspace)
    db_session.flush()

    membership = WorkspaceMembership(
        workspace=workspace,
        user=owner,
        role="owner",
    )
    db_session.add(membership)
    db_session.flush()

    assert membership.workspace_id == workspace.id
    assert membership.user_id == owner.id


def test_workspace_membership_constraints(db_session: Session) -> None:
    owner = User(email="membership-owner@example.invalid", account_status="active")
    member = User(email="membership-member@example.invalid", account_status="active")
    workspace = Workspace(name="Membership Test", slug="membership-test", owner=owner)
    db_session.add_all([owner, member, workspace])
    db_session.flush()

    db_session.add(WorkspaceMembership(workspace=workspace, user=member, role="owner"))
    db_session.flush()
    db_session.add(WorkspaceMembership(workspace=workspace, user=member, role="member"))
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()

    invalid_owner = User(email="invalid-role-owner@example.invalid", account_status="active")
    invalid_member = User(email="invalid-role-member@example.invalid", account_status="active")
    workspace = Workspace(
        name="Invalid Role",
        slug="invalid-role",
        owner=invalid_owner,
    )
    db_session.add_all([invalid_owner, invalid_member, workspace])
    db_session.flush()
    db_session.add(
        WorkspaceMembership(
            workspace=workspace,
            user=invalid_member,
            role="superuser",
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_workflow_names_are_unique_only_within_a_workspace(db_session: Session) -> None:
    owner = User(email="workspace-owner@example.invalid", account_status="active")
    db_session.add(owner)
    db_session.flush()
    workspace_a = Workspace(name="Workspace A", slug="workspace-a", owner=owner)
    workspace_b = Workspace(name="Workspace B", slug="workspace-b", owner=owner)
    db_session.add_all([workspace_a, workspace_b])
    db_session.flush()

    db_session.add(
        Workflow(
            name="shared-name",
            workflow_definition={},
            version=1,
            workspace=workspace_a,
            created_by=owner,
            updated_by=owner,
        )
    )
    db_session.flush()
    db_session.add(
        Workflow(
            name="shared-name",
            workflow_definition={},
            version=1,
            workspace=workspace_b,
            created_by=owner,
            updated_by=owner,
        )
    )
    db_session.flush()

    db_session.add(
        Workflow(
            name="shared-name",
            workflow_definition={},
            version=1,
            workspace=workspace_a,
            created_by=owner,
            updated_by=owner,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


def test_execution_inherits_and_preserves_workspace_ownership(db_session: Session) -> None:
    owner = User(email="execution-owner@example.invalid", account_status="active")
    db_session.add(owner)
    db_session.flush()
    workspace = Workspace(name="Execution Workspace", slug="execution-workspace", owner=owner)
    db_session.add(workspace)
    db_session.flush()
    workflow = Workflow(
        name="owned-workflow",
        workflow_definition={},
        version=1,
        workspace=workspace,
        created_by=owner,
        updated_by=owner,
    )
    db_session.add(workflow)
    db_session.flush()
    execution = WorkflowExecution(
        workflow=workflow,
        workspace=workspace,
        created_by=owner,
        original_task="Owned task",
        status="pending",
    )
    db_session.add(execution)
    db_session.flush()

    assert execution.workspace_id == workflow.workspace_id
    assert execution.created_by_user_id == owner.id


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
    legacy_workspace = _legacy_workspace(db_session)
    event = ExecutionEvent(
        execution=WorkflowExecution(
            original_task="Audit this",
            status="submitted",
            workspace=legacy_workspace,
        ),
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


def test_upgrade_backfills_existing_workflow_and_execution_to_legacy_workspace(
    migrated_database: Engine,
) -> None:
    with migrated_database.begin() as connection:
        command.downgrade(_alembic_config(connection), "7f2c9b1e4a6d")

    workflow_id = uuid4()
    execution_id = uuid4()
    with migrated_database.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO workflows (
                    id, name, workflow_definition, version,
                    created_at, updated_at
                )
                VALUES (
                    :workflow_id,
                    'existing-legacy-workflow',
                    '{}'::jsonb,
                    1,
                    now(),
                    now()
                )
                """
            ),
            {"workflow_id": workflow_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO workflow_executions (
                    id, workflow_id, original_task, status, created_at
                )
                VALUES (
                    :execution_id,
                    :workflow_id,
                    'Existing legacy execution',
                    'pending',
                    now()
                )
                """
            ),
            {"execution_id": execution_id, "workflow_id": workflow_id},
        )

    with migrated_database.begin() as connection:
        command.upgrade(_alembic_config(connection), "head")

    with Session(migrated_database) as session:
        legacy = _legacy_workspace(session)
        workflow = session.get(Workflow, workflow_id)
        execution = session.get(WorkflowExecution, execution_id)
        assert workflow is not None
        assert execution is not None
        assert workflow.workspace_id == legacy.id
        assert workflow.created_by_user_id == legacy.owner_id
        assert workflow.updated_by_user_id == legacy.owner_id
        assert execution.workspace_id == legacy.id
        assert execution.workflow_id == workflow.id
        assert execution.created_by_user_id == legacy.owner_id


def _create_persisted_execution(
    session: Session,
    *,
    definition: WorkflowDefinition,
    engine: WorkflowEngine | None = None,
) -> tuple[Workflow, WorkflowEngine, ExecutionRepository, WorkflowExecutionSnapshot]:
    legacy_workspace = _legacy_workspace(session)
    workflow = Workflow(
        name=f"execution-test-{uuid4().hex}",
        description="A persisted workflow.",
        workflow_definition=definition.model_dump(mode="json"),
        version=1,
        workspace=legacy_workspace,
        created_by=legacy_workspace.owner,
        updated_by=legacy_workspace.owner,
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
        legacy_workspace = _legacy_workspace(session)
        workflow = Workflow(
            name=f"rollback-{uuid4().hex}",
            workflow_definition=definition.model_dump(mode="json"),
            version=1,
            workspace=legacy_workspace,
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


def _approval_tool_registry() -> ToolRegistry:
    """Create a tool registry with a single tool that requires approval."""

    def guarded_handler(payload: object) -> dict[str, object]:
        return {"result": "ok"}

    tool = ToolDefinition(
        tool_id="guarded_tool",
        name="guarded_tool",
        description="Requires approval before use.",
        required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
        requires_approval=True,
        approval_description="Approval required before this tool is invoked.",
        handler=guarded_handler,
    )
    return ToolRegistry([tool])


def _create_minimal_execution(session: Session) -> UUID:
    """Create a minimal workflow execution and return its ID."""
    legacy_workspace = _legacy_workspace(session)
    workflow = Workflow(
        name=f"wf-{uuid4().hex}",
        description="Minimal workflow for approval tests.",
        workflow_definition={"schema_version": 1, "steps": []},
        version=1,
        workspace=legacy_workspace,
    )
    session.add(workflow)
    session.flush()
    execution = WorkflowExecution(
        workflow_id=workflow.id,
        workspace_id=legacy_workspace.id,
        original_task="Test task",
        status="pending",
    )
    session.add(execution)
    session.flush()
    session.commit()
    return execution.id


def test_approval_request_is_persisted_as_pending(migrated_database: Engine) -> None:
    """A newly created approval request is durably stored with pending status."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            tool_id="guarded_tool",
            action_description="Approve executing tool guarded_tool for task task-1.",
            action_digest="a" * 64,
            safe_arguments={"message": "test"},
        )
        session.commit()

    assert approval.id is not None
    assert approval.execution_id == execution_id
    assert approval.tool_id == "guarded_tool"
    assert approval.status == "pending"
    assert approval.reviewed_at is None
    assert approval.requested_at is not None

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        pending = repository.get_pending_approval_requests(execution_id=execution_id)
        assert len(pending) == 1
        assert pending[0].status == "pending"
        assert pending[0].action_digest == "a" * 64


def test_approval_decision_is_persisted_as_approved(migrated_database: Engine) -> None:
    """Approving a pending request persists the approved status and review time."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            action_description="Test approval",
            action_digest="a" * 64,
            safe_arguments={"key": "value"},
        )
        session.commit()
        approval_id = approval.id

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        updated = repository.approve_approval_request(approval_id)
        assert updated.status == "approved"
        assert updated.reviewed_at is not None

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        pending = repository.get_pending_approval_requests(execution_id=execution_id)
        assert len(pending) == 0

        record = repository.get_approval_request_by_id(approval_id)
        assert record is not None
        assert record.status == "approved"


def test_rejection_decision_is_persisted_as_rejected(migrated_database: Engine) -> None:
    """Rejecting a pending request persists the rejected status and review time."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            action_description="Test approval",
            action_digest="a" * 64,
            safe_arguments={"key": "value"},
        )
        session.commit()
        approval_id = approval.id

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        updated = repository.reject_approval_request(approval_id)
        assert updated.status == "rejected"
        assert updated.reviewed_at is not None

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        pending = repository.get_pending_approval_requests(execution_id=execution_id)
        assert len(pending) == 0

        record = repository.get_approval_request_by_id(approval_id)
        assert record is not None
        assert record.status == "rejected"


def test_approve_already_reviewed_approval_raises_error(migrated_database: Engine) -> None:
    """Approving an already-approved or rejected request raises an error."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            action_description="Test approval",
            action_digest="a" * 64,
            safe_arguments={},
        )
        repository.approve_approval_request(approval.id)
        session.commit()

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        with pytest.raises(ExecutionPersistenceError, match="not pending"):
            repository.approve_approval_request(approval.id)

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        with pytest.raises(ExecutionPersistenceError, match="not pending"):
            repository.reject_approval_request(approval.id)


def test_reject_already_reviewed_approval_raises_error(migrated_database: Engine) -> None:
    """Rejecting an already-approved or rejected request raises an error."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            action_description="Test approval",
            action_digest="a" * 64,
            safe_arguments={},
        )
        repository.reject_approval_request(approval.id)

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        with pytest.raises(ExecutionPersistenceError, match="not pending"):
            repository.reject_approval_request(approval.id)

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        with pytest.raises(ExecutionPersistenceError, match="not pending"):
            repository.approve_approval_request(approval.id)


def test_approval_request_not_found_raises_error(migrated_database: Engine) -> None:
    """Operating on a non-existent approval request raises an error."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        with pytest.raises(ExecutionPersistenceError, match="was not found"):
            repository.approve_approval_request(uuid4())
        with pytest.raises(ExecutionPersistenceError, match="was not found"):
            repository.reject_approval_request(uuid4())


def test_database_transaction_failure_preserves_in_memory_state(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed database transaction does not falsely update approval state."""
    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        execution_id = _create_minimal_execution(session)
        approval = repository.create_approval_request(
            execution_id=execution_id,
            execution_step_id=None,
            action_description="Test approval",
            action_digest="a" * 64,
            safe_arguments={},
        )
        approval_id = approval.id
        session.commit()

        def failing_commit() -> None:
            raise RuntimeError("controlled commit failure")

        monkeypatch.setattr(session, "commit", failing_commit)

        with pytest.raises(ExecutionPersistenceError):
            repository.approve_approval_request(approval_id)

    with Session(migrated_database) as session:
        repository = ExecutionRepository(session)
        pending = repository.get_pending_approval_requests(execution_id=execution_id)
        assert len(pending) == 1
        assert pending[0].status == "pending"
        assert pending[0].reviewed_at is None


def test_engine_persists_approval_request_through_repository(
    migrated_database: Engine,
) -> None:
    """The WorkflowEngine persists approval requests via the repository."""
    registry = _approval_tool_registry()
    definition = WorkflowDefinition(
        name="approval persistence test",
        tasks=[
            WorkflowTask(
                task_id="research",
                agent_type=AgentRole.ANALYST,
                tool_request=WorkflowToolRequest(
                    tool_id="guarded_tool",
                    arguments={"message": "search"},
                ),
            )
        ],
    )

    with Session(migrated_database) as session:
        legacy_workspace = _legacy_workspace(session)
        workflow = Workflow(
            name=f"approval-test-{uuid4().hex}",
            description="Approval persistence test.",
            workflow_definition=definition.model_dump(mode="json"),
            version=1,
            workspace=legacy_workspace,
        )
        session.add(workflow)
        session.commit()

        repository = ExecutionRepository(session)
        engine = WorkflowEngine(
            tool_executor=ToolExecutor(registry),
            approval_repository=repository,
        )

        snapshot = engine.create_execution(
            definition,
            on_update=lambda value: repository.create_execution(
                value,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                definition=definition,
            ),
        )

        waiting = engine.run(snapshot.execution_id, on_update=repository.synchronize_execution)
        assert waiting.status == WorkflowStatus.WAITING_APPROVAL

        pending = repository.get_pending_approval_requests(execution_id=snapshot.execution_id)
        assert len(pending) == 1
        assert pending[0].status == "pending"
        assert pending[0].action_digest is not None
        assert len(pending[0].action_digest) == 64

        resumed = engine.approve(
            snapshot.execution_id,
            approved=True,
            on_update=repository.synchronize_execution,
        )
        assert resumed.status == WorkflowStatus.COMPLETED

        record = repository.get_approval_request_by_id(pending[0].id)
        assert record is not None
        assert record.status == "approved"
        assert record.reviewed_at is not None
        assert repository.get_execution(snapshot.execution_id).status == WorkflowStatus.COMPLETED

        remaining = repository.get_pending_approval_requests(execution_id=snapshot.execution_id)
        assert len(remaining) == 0


def test_engine_does_not_authorize_when_approval_commit_fails(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed approval transaction leaves the tool grant pending and unusable."""
    invoked: list[bool] = []
    registry = ToolRegistry(
        [
            ToolDefinition(
                tool_id="guarded_tool",
                name="guarded_tool",
                description="Requires approval before use.",
                required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
                requires_approval=True,
                handler=lambda _payload: invoked.append(True) or {"result": "ok"},
            )
        ]
    )
    definition = WorkflowDefinition(
        name="approval transaction failure",
        tasks=[
            WorkflowTask(
                task_id="research",
                agent_type=AgentRole.ANALYST,
                tool_request=WorkflowToolRequest(
                    tool_id="guarded_tool", arguments={"message": "search"}
                ),
            )
        ],
    )
    with Session(migrated_database) as session:
        legacy_workspace = _legacy_workspace(session)
        workflow = Workflow(
            name=f"approval-failure-{uuid4().hex}",
            description="Approval transaction failure test.",
            workflow_definition=definition.model_dump(mode="json"),
            version=1,
            workspace=legacy_workspace,
        )
        session.add(workflow)
        session.commit()
        repository = ExecutionRepository(session)
        engine = WorkflowEngine(
            tool_executor=ToolExecutor(registry), approval_repository=repository
        )
        pending = engine.create_execution(
            definition,
            on_update=lambda value: repository.create_execution(
                value,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                definition=definition,
            ),
        )
        waiting = engine.run(pending.execution_id, on_update=repository.synchronize_execution)
        grant = engine._pending_approvals[(pending.execution_id, "research")]
        assert waiting.status == WorkflowStatus.WAITING_APPROVAL

        def fail_approval(_approval_id: UUID, *, commit: bool = True) -> None:
            raise ExecutionPersistenceError("controlled transaction failure")

        monkeypatch.setattr(repository, "approve_approval_request", fail_approval)
        with pytest.raises(ExecutionPersistenceError):
            engine.approve(pending.execution_id, approved=True)

        assert grant.status == "pending"
        assert grant.approval_id in engine._approval_registry
        assert invoked == []
        assert engine.get_execution(pending.execution_id).status == WorkflowStatus.WAITING_APPROVAL


def test_approval_api_auth_binding_review_and_health(
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Approval endpoints authenticate operators and bind reviews to one execution."""
    token = "approval-operator-token-" + "x" * 20
    settings = Settings(_env_file=None, app_env="test", api_access_token=SecretStr(token))
    application = create_app(settings)
    calls: list[dict[str, object]] = []

    def guarded_handler(payload: object) -> dict[str, object]:
        calls.append(payload if isinstance(payload, dict) else {"payload": payload})
        return {"ok": True}

    registry = ToolRegistry(
        [
            ToolDefinition(
                tool_id="guarded_tool",
                name="guarded_tool",
                description="Operator-gated test action.",
                required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
                requires_approval=True,
                handler=guarded_handler,
            )
        ]
    )

    with TestClient(application) as client:
        engine = WorkflowEngine(tool_executor=ToolExecutor(registry), settings=settings)
        application.state.workflow_engine = engine
        public_health = client.get("/api/v1/health")

        def start_waiting_execution() -> tuple[str, str]:
            workflow = client.post(
                "/api/v1/workflows",
                json={
                    "name": f"approval-api-{uuid4().hex}",
                    "tasks": [
                        {
                            "task_id": "guarded",
                            "agent_type": "analyst",
                            "tool_request": {
                                "tool_id": "guarded_tool",
                                "arguments": {"message": "sensitive-marker"},
                            },
                        }
                    ],
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            assert workflow.status_code == 201, workflow.text
            execution = client.post(
                f"/api/v1/workflows/{workflow.json()['id']}/executions",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert execution.status_code == 201, execution.text
            execution_id = execution.json()["execution_id"]
            started = client.post(
                f"/api/v1/executions/{execution_id}/start",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert started.status_code == 200, started.text
            assert started.json()["status"] == "waiting_approval"
            return execution_id, started.json()["task_results"]["guarded"]["tool_result"][
                "metadata"
            ]["approval_grant_id"]

        first_execution, first_approval = start_waiting_execution()
        approval_url = f"/api/v1/executions/{first_execution}/approvals"
        assert client.get(approval_url).status_code == 401
        assert (
            client.get(approval_url, headers={"Authorization": "Bearer wrong"}).status_code == 401
        )
        listing = client.get(approval_url, headers={"Authorization": f"Bearer {token}"})
        assert listing.status_code == 200
        assert listing.json()[0]["approval_id"] == str(UUID(first_approval))
        assert "safe_arguments" not in listing.text
        assert "sensitive-marker" not in listing.text
        wrong_execution = uuid4()
        cross_review = client.post(
            f"/api/v1/executions/{wrong_execution}/approvals/{first_approval}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cross_review.status_code == 404

        approved = client.post(
            f"/api/v1/executions/{first_execution}/approvals/{first_approval}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"
        assert len(calls) == 1
        repeated = client.post(
            f"/api/v1/executions/{first_execution}/approvals/{first_approval}/approve",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert repeated.status_code == 409

        second_execution, second_approval = start_waiting_execution()
        rejected = client.post(
            f"/api/v1/executions/{second_execution}/approvals/{second_approval}/reject",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert rejected.status_code == 200, rejected.text
        assert rejected.json()["status"] == "failed"
        assert len(calls) == 1
        repeated_rejection = client.post(
            f"/api/v1/executions/{second_execution}/approvals/{second_approval}/reject",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert repeated_rejection.status_code == 409

        cancelled_execution, cancelled_approval = start_waiting_execution()
        cancelled = client.post(
            f"/api/v1/executions/{cancelled_execution}/cancel",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert cancelled.status_code == 200, cancelled.text
        assert cancelled.json()["status"] == "cancelled"
        assert len(calls) == 1
        with Session(migrated_database) as session:
            cancelled_row = ExecutionRepository(session).get_approval_request_by_id(
                UUID(cancelled_approval)
            )
            assert cancelled_row is not None
            assert cancelled_row.status == "rejected"

        failed_execution, failed_approval = start_waiting_execution()
        with monkeypatch.context() as patch_context:

            def fail_decision(_repository, _approval_id: UUID, *, commit: bool = True):
                raise ExecutionPersistenceError("controlled API persistence failure")

            patch_context.setattr(ExecutionRepository, "approve_approval_request", fail_decision)
            failed_review = client.post(
                f"/api/v1/executions/{failed_execution}/approvals/{failed_approval}/approve",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert failed_review.status_code == 503
        assert len(calls) == 1

        failed_execution, failed_approval = start_waiting_execution()
        with monkeypatch.context() as patch_context:

            def fail_execution_update(_repository, _snapshot) -> None:
                raise ExecutionPersistenceError("controlled execution transaction failure")

            patch_context.setattr(
                ExecutionRepository,
                "synchronize_execution",
                fail_execution_update,
            )
            failed_review = client.post(
                f"/api/v1/executions/{failed_execution}/approvals/{failed_approval}/approve",
                headers={"Authorization": f"Bearer {token}"},
            )
        assert failed_review.status_code == 503
        assert len(calls) == 1
        with Session(migrated_database) as session:
            repository = ExecutionRepository(session)
            durable_approval = repository.get_approval_request_by_id(UUID(failed_approval))
            durable_execution = repository.get_execution(UUID(failed_execution))
            assert durable_approval is not None
            assert durable_approval.status == "pending"
            assert durable_execution.status == WorkflowStatus.WAITING_APPROVAL

    assert public_health.status_code == 200


def test_openai_browser_session_authenticates_workflow_execution_and_approvals(
    migrated_database: Engine,
) -> None:
    """A browser session protects the full OpenAI-mode operator workflow."""
    origin = "http://localhost:5173"
    token = "browser-flow-operator-token-" + "x" * 16
    settings = Settings(
        _env_file=None,
        app_env="test",
        provider_mode="openai",
        openai_api_key=SecretStr("provider-key-for-test"),
        api_access_token=SecretStr(token),
        session_signing_secret=SecretStr("b" * 40),
        cors_origins=[origin],
    )
    application = create_app(settings)
    calls: list[object] = []

    def guarded_handler(payload: object) -> dict[str, bool]:
        calls.append(payload)
        return {"ok": True}

    registry = ToolRegistry(
        [
            ToolDefinition(
                tool_id="browser_guarded_tool",
                name="browser_guarded_tool",
                description="Requires operator approval.",
                required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
                requires_approval=True,
                handler=guarded_handler,
            )
        ]
    )
    with TestClient(application) as client:
        application.state.workflow_engine = WorkflowEngine(
            tool_executor=ToolExecutor(registry), settings=settings
        )
        assert client.get("/api/v1/workflows").status_code == 401
        assert client.get("/api/v1/executions").status_code == 401

        login = client.post(
            "/api/v1/auth/session",
            json={"credential": token},
            headers={"Origin": origin},
        )
        assert login.status_code == 200, login.text
        assert client.get("/api/v1/auth/session").json() == {"authenticated": True}

        workflow = client.post(
            "/api/v1/workflows",
            json={
                "name": f"browser-session-{uuid4().hex}",
                "tasks": [
                    {
                        "task_id": "guarded",
                        "agent_type": "analyst",
                        "tool_request": {
                            "tool_id": "browser_guarded_tool",
                            "arguments": {"message": "private-action-argument"},
                        },
                    }
                ],
            },
            headers={"Origin": origin},
        )
        assert workflow.status_code == 201, workflow.text
        workflow_id = workflow.json()["id"]
        fetched_workflow = client.get(f"/api/v1/workflows/{workflow_id}")
        assert fetched_workflow.status_code == 200, fetched_workflow.text
        execution = client.post(
            f"/api/v1/workflows/{workflow_id}/executions", headers={"Origin": origin}
        )
        assert execution.status_code == 201, execution.text
        execution_id = execution.json()["execution_id"]
        fetched_execution = client.get(f"/api/v1/executions/{execution_id}")
        assert fetched_execution.status_code == 200, fetched_execution.text
        started = client.post(
            f"/api/v1/executions/{execution_id}/start", headers={"Origin": origin}
        )
        assert started.status_code == 200, started.text
        assert started.json()["status"] == "waiting_approval"

        approvals_url = f"/api/v1/executions/{execution_id}/approvals"
        approvals = client.get(approvals_url)
        assert approvals.status_code == 200, approvals.text
        approval = approvals.json()[0]
        assert approval["status"] == "pending"
        assert "private-action-argument" not in approvals.text
        assert "arguments" not in approval

        wrong_origin = client.post(
            f"{approvals_url}/{approval['approval_id']}/approve",
            headers={"Origin": "https://attacker.example"},
        )
        assert wrong_origin.status_code == 403
        approved = client.post(
            f"{approvals_url}/{approval['approval_id']}/approve",
            headers={"Origin": origin},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "completed"
        assert len(calls) == 1
        refreshed = client.get(approvals_url)
        assert refreshed.status_code == 200
        assert refreshed.json()[0]["status"] == "approved"

        logout = client.delete("/api/v1/auth/session", headers={"Origin": origin})
        assert logout.status_code == 204
        assert client.get("/api/v1/workflows").status_code == 401
        assert client.get("/api/v1/executions").status_code == 401
        assert client.get(approvals_url).status_code == 401
