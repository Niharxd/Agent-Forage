import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
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
from agentforge.main import create_app
from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text, update
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

        with engine.connect() as connection:
            command.upgrade(_alembic_config(connection), "head")

        yield engine
    finally:
        try:
            with engine.begin() as connection:
                Base.metadata.drop_all(connection)
                connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
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
