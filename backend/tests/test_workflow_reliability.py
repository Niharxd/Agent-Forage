from datetime import UTC, datetime
from threading import Event, Thread
from uuid import UUID, uuid4

import pytest
from agentforge.agents import AnalystAgent, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentforge.config.settings import Settings
from agentforge.domain.agents import (
    Agent,
    AgentError,
    AgentErrorCode,
    AgentExecutionError,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentInput,
    AgentOutput,
    AgentRole,
)
from agentforge.domain.agents.interface import AgentInputValue, AgentOutputValue
from agentforge.domain.workflows import (
    TaskExecutionResult,
    TaskStatus,
    WorkflowEventType,
    WorkflowExecution,
    WorkflowExecutionSnapshot,
    WorkflowStateTransitionError,
    WorkflowStatus,
    WorkflowTaskError,
    WorkflowValidationError,
)
from agentforge.workflow import (
    ExecutionNotFoundError,
    InvalidExecutionStateError,
    WorkflowEngine,
)
from pydantic import ValidationError


def task(task_id: str, *, dependencies: list[str] | None = None) -> dict[str, object]:
    return {
        "task_id": task_id,
        "agent_type": "analyst",
        "dependency_ids": dependencies or [],
    }


def definition(*tasks: dict[str, object]) -> dict[str, object]:
    return {"name": "reliability workflow", "tasks": list(tasks)}


def mock_agents(**replacements: Agent) -> dict[AgentRole, Agent]:
    agents: dict[AgentRole, Agent] = {
        AgentRole.PLANNER: PlannerAgent(),
        AgentRole.RESEARCHER: ResearcherAgent(),
        AgentRole.ANALYST: AnalystAgent(),
        AgentRole.REVIEWER: ReviewerAgent(),
    }
    agents.update({AgentRole(role): agent for role, agent in replacements.items()})
    return agents


class ClassifiedFailingAnalyst(AnalystAgent):
    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        raise AgentExecutionError(
            AgentError(
                code=AgentErrorCode.INTERNAL_AGENT_ERROR,
                message="secret-value must never appear in a result",
                details={"private": "secret-value"},
            )
        )


class LargeOutputAnalyst(AnalystAgent):
    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            summary="Produced a large output.",
            result_data={"payload": "x" * 1_000},
        ).model_dump(mode="python")


class CountingAnalyst(AnalystAgent):
    def __init__(self) -> None:
        self.calls = 0

    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        self.calls += 1
        return super()._execute(agent_input)


class BlockingAnalyst(AnalystAgent):
    def __init__(self, entered: Event, release: Event) -> None:
        self.entered = entered
        self.release = release

    def execute(self, value: AgentInputValue) -> AgentExecutionResult:
        self.entered.set()
        if not self.release.wait(timeout=5):
            raise TimeoutError("test release was not signalled")
        return super().execute(value)


def test_workflow_transition_rules_allow_only_documented_paths() -> None:
    execution = WorkflowExecution(
        workflow={"tasks": [task("one")]},
        task_results={
            "one": TaskExecutionResult(task_id="one", agent_type="analyst", status="pending")
        },
    )
    execution.transition_to(WorkflowStatus.RUNNING)
    execution.transition_to(WorkflowStatus.COMPLETED)

    assert execution.status == WorkflowStatus.COMPLETED
    with pytest.raises(WorkflowStateTransitionError):
        execution.transition_to(WorkflowStatus.RUNNING)

    pending = WorkflowExecution(
        workflow={"tasks": [task("one")]},
        task_results={
            "one": TaskExecutionResult(task_id="one", agent_type="analyst", status="pending")
        },
    )
    pending.transition_to(WorkflowStatus.CANCELLED)
    with pytest.raises(WorkflowStateTransitionError):
        pending.transition_to(WorkflowStatus.RUNNING)


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.RUNNING),
        (TaskStatus.PENDING, TaskStatus.BLOCKED),
        (TaskStatus.PENDING, TaskStatus.SKIPPED),
        (TaskStatus.RUNNING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.FAILED),
    ],
)
def test_task_transition_rules_allow_documented_paths(
    initial: TaskStatus,
    target: TaskStatus,
) -> None:
    result = TaskExecutionResult(task_id="one", agent_type="analyst", status=initial)

    result.transition_to(target)

    assert result.status == target


@pytest.mark.parametrize(
    ("initial", "target"),
    [
        (TaskStatus.PENDING, TaskStatus.COMPLETED),
        (TaskStatus.RUNNING, TaskStatus.SKIPPED),
        (TaskStatus.COMPLETED, TaskStatus.RUNNING),
        (TaskStatus.FAILED, TaskStatus.RUNNING),
        (TaskStatus.BLOCKED, TaskStatus.COMPLETED),
        (TaskStatus.SKIPPED, TaskStatus.RUNNING),
    ],
)
def test_task_transition_rules_reject_invalid_paths(
    initial: TaskStatus,
    target: TaskStatus,
) -> None:
    result = TaskExecutionResult(task_id="one", agent_type="analyst", status=initial)

    with pytest.raises(WorkflowStateTransitionError):
        result.transition_to(target)


@pytest.mark.parametrize(
    "terminal_status",
    [
        WorkflowStatus.COMPLETED,
        WorkflowStatus.FAILED,
        WorkflowStatus.CANCELLED,
    ],
)
def test_terminal_workflow_states_cannot_restart(
    terminal_status: WorkflowStatus,
) -> None:
    execution = WorkflowExecution(
        workflow={"tasks": [task("one")]},
        status=terminal_status,
        task_results={
            "one": TaskExecutionResult(task_id="one", agent_type="analyst", status="pending")
        },
        completed_at=datetime.now(UTC),
    )

    with pytest.raises(WorkflowStateTransitionError):
        execution.transition_to(WorkflowStatus.RUNNING)


def test_initial_snapshot_is_serializable_and_contains_pending_task_state() -> None:
    engine = WorkflowEngine()

    snapshot = engine.create_execution(definition(task("one")))
    serialized = WorkflowExecutionSnapshot.model_validate_json(snapshot.model_dump_json())

    assert snapshot.status == WorkflowStatus.PENDING
    assert snapshot.started_at is None
    assert snapshot.completed_at is None
    assert snapshot.created_at.tzinfo is not None
    assert snapshot.task_results["one"].status == TaskStatus.PENDING
    assert snapshot.events == []
    assert serialized == snapshot


def test_successful_snapshot_captures_lifecycle_results_and_order() -> None:
    engine = WorkflowEngine()
    initial = engine.create_execution(definition(task("b"), task("a")))

    execution = engine.run(initial.execution_id)
    snapshot = engine.get_execution(initial.execution_id)

    assert execution.status == WorkflowStatus.COMPLETED
    assert snapshot.workflow_name == "reliability workflow"
    assert snapshot.status == WorkflowStatus.COMPLETED
    assert snapshot.started_at is not None and snapshot.completed_at is not None
    assert snapshot.execution_order == ["a", "b"]
    assert all(result.status == TaskStatus.COMPLETED for result in snapshot.task_results.values())
    assert [event.event_type for event in snapshot.events][0] == WorkflowEventType.WORKFLOW_STARTED
    assert snapshot.events[-1].event_type == WorkflowEventType.WORKFLOW_COMPLETED


def test_failed_snapshot_has_sanitized_error_category_and_timestamp() -> None:
    engine = WorkflowEngine(agents=mock_agents(analyst=ClassifiedFailingAnalyst()))

    execution = engine.execute(definition(task("one")))
    snapshot = engine.get_execution(execution.execution_id)
    task_result = snapshot.task_results["one"]
    serialized = snapshot.model_dump_json()

    assert snapshot.status == WorkflowStatus.FAILED
    assert task_result.status == TaskStatus.FAILED
    assert task_result.task_id == "one"
    assert task_result.agent_type == AgentRole.ANALYST
    assert task_result.error is not None
    assert task_result.error.code == AgentErrorCode.INTERNAL_AGENT_ERROR.value
    assert task_result.error.message == "The agent encountered an internal error."
    assert task_result.error.occurred_at == task_result.completed_at
    assert "secret-value" not in serialized
    assert task_result.agent_result is None


def test_snapshot_rejects_inconsistent_terminal_state() -> None:
    with pytest.raises(ValidationError, match="completed_at"):
        WorkflowExecutionSnapshot(
            execution_id=uuid4(),
            workflow_name="bad",
            status=WorkflowStatus.COMPLETED,
            created_at=datetime.now(UTC),
            task_results={
                "one": TaskExecutionResult(
                    task_id="one",
                    agent_type="analyst",
                    status=TaskStatus.PENDING,
                )
            },
            events=[],
            execution_order=[],
        )

    with pytest.raises(ValidationError, match="active tasks"):
        WorkflowExecutionSnapshot(
            execution_id=uuid4(),
            workflow_name="inconsistent",
            status=WorkflowStatus.COMPLETED,
            created_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
            completed_at=datetime.now(UTC),
            task_results={
                "one": TaskExecutionResult(
                    task_id="one",
                    agent_type="analyst",
                    status=TaskStatus.PENDING,
                )
            },
            events=[],
            execution_order=[],
        )


def test_task_input_limit_is_rejected_before_agent_dispatch() -> None:
    analyst = CountingAnalyst()
    settings = Settings(_env_file=None, workflow_max_task_input_bytes=20)
    engine = WorkflowEngine(agents=mock_agents(analyst=analyst), settings=settings)

    with pytest.raises(WorkflowValidationError, match="input"):
        engine.create_execution(definition({**task("one"), "input_data": {"payload": "x" * 30}}))

    assert analyst.calls == 0


def test_combined_agent_input_limit_is_checked_before_dispatch() -> None:
    analyst = CountingAnalyst()
    settings = Settings(_env_file=None, workflow_max_task_input_bytes=500)
    engine = WorkflowEngine(agents=mock_agents(analyst=analyst), settings=settings)
    oversized_task = {
        **task("one"),
        "description": "x" * 600,
        "input_data": {},
    }

    execution = engine.execute(definition(oversized_task))

    assert execution.status == WorkflowStatus.FAILED
    assert execution.task_results["one"].error.code == "task_input_limit"
    assert analyst.calls == 0


def test_maximum_workflow_task_count_is_configurable() -> None:
    engine = WorkflowEngine(
        settings=Settings(_env_file=None, workflow_max_tasks=1),
    )

    with pytest.raises(WorkflowValidationError, match="more than"):
        engine.create_execution(definition(task("one"), task("two")))


def test_execution_step_limit_fails_clearly_and_skips_remaining_work() -> None:
    settings = Settings(_env_file=None, workflow_max_execution_steps=1)
    engine = WorkflowEngine(settings=settings)

    execution = engine.execute(definition(task("one"), task("two")))

    assert execution.status == WorkflowStatus.FAILED
    assert execution.task_results["one"].status == TaskStatus.COMPLETED
    assert execution.task_results["two"].status == TaskStatus.SKIPPED
    assert execution.task_results["two"].error.code == "execution_step_limit"
    assert WorkflowEventType.EXECUTION_LIMIT_REACHED in [
        event.event_type for event in execution.events
    ]


def test_excessive_result_is_failed_without_retaining_oversized_content() -> None:
    engine = WorkflowEngine(
        agents=mock_agents(analyst=LargeOutputAnalyst()),
        settings=Settings(_env_file=None, workflow_max_result_bytes=100),
    )

    execution = engine.execute(definition(task("one")))
    result = execution.task_results["one"]

    assert execution.status == WorkflowStatus.FAILED
    assert result.status == TaskStatus.FAILED
    assert result.error.code == "result_too_large"
    assert result.agent_result is None


def test_cancel_pending_execution_skips_tasks_and_records_cancellation() -> None:
    engine = WorkflowEngine()
    pending = engine.create_execution(definition(task("one"), task("two")))

    snapshot = engine.cancel(pending.execution_id)

    assert snapshot.status == WorkflowStatus.CANCELLED
    assert snapshot.completed_at is not None
    assert all(result.status == TaskStatus.SKIPPED for result in snapshot.task_results.values())
    assert [event.event_type for event in snapshot.events][
        -1
    ] == WorkflowEventType.WORKFLOW_CANCELLED
    assert engine.list_executions()[0].execution_id == pending.execution_id


def test_running_cancellation_waits_for_current_agent_and_preserves_its_result() -> None:
    entered = Event()
    release = Event()
    blocking = BlockingAnalyst(entered, release)
    engine = WorkflowEngine(agents=mock_agents(analyst=blocking))
    pending = engine.create_execution(definition(task("a-first"), task("b-second")))
    results: list[WorkflowExecution] = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            results.append(engine.run(pending.execution_id))
        except BaseException as exc:
            errors.append(exc)

    worker = Thread(target=run)
    worker.start()
    try:
        assert entered.wait(timeout=2)
        requested = engine.cancel(pending.execution_id)
        assert requested.status == WorkflowStatus.RUNNING
        assert requested.cancellation_requested is True
        assert requested.task_results["a-first"].status == TaskStatus.RUNNING
        assert requested.task_results["b-second"].status == TaskStatus.PENDING
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    assert errors == []
    assert len(results) == 1
    execution = results[0]
    assert execution.status == WorkflowStatus.CANCELLED
    assert execution.task_results["a-first"].status == TaskStatus.COMPLETED
    assert execution.task_results["a-first"].agent_result is not None
    assert execution.task_results["b-second"].status == TaskStatus.SKIPPED
    assert execution.execution_order == ["a-first"]
    event_types = [event.event_type for event in execution.events]
    assert WorkflowEventType.WORKFLOW_CANCELLATION_REQUESTED in event_types
    assert WorkflowEventType.WORKFLOW_CANCELLED in event_types


def test_history_retrieves_snapshots_lists_recent_and_evicts_oldest() -> None:
    engine = WorkflowEngine(settings=Settings(_env_file=None, workflow_history_size=2))
    execution_ids = [
        engine.execute(definition(task(f"task-{index}"))).execution_id for index in range(3)
    ]

    recent = engine.list_executions()

    assert [snapshot.execution_id for snapshot in recent] == execution_ids[2:0:-1]
    assert [snapshot.execution_id for snapshot in engine.list_executions(limit=1)] == [
        execution_ids[-1]
    ]
    assert engine.get_execution(execution_ids[-1]).status == WorkflowStatus.COMPLETED
    with pytest.raises(ExecutionNotFoundError):
        engine.get_execution(execution_ids[0])


def test_history_snapshots_are_detached_from_mutation() -> None:
    engine = WorkflowEngine()
    execution = engine.execute(definition(task("one")))
    retrieved = engine.get_execution(execution.execution_id)
    retrieved.task_results["one"].status = TaskStatus.FAILED
    retrieved.execution_order.append("forged")

    stored = engine.get_execution(execution.execution_id)
    assert stored.task_results["one"].status == TaskStatus.COMPLETED
    assert stored.execution_order == ["one"]


def test_unknown_execution_and_terminal_rerun_are_reported() -> None:
    engine = WorkflowEngine()
    unknown_id = UUID("a7a60f6a-6a91-4312-9462-e7b3db790941")
    with pytest.raises(ExecutionNotFoundError):
        engine.get_execution(unknown_id)
    with pytest.raises(ExecutionNotFoundError):
        engine.cancel(unknown_id)

    execution = engine.execute(definition(task("one")))
    with pytest.raises(InvalidExecutionStateError, match="terminal"):
        engine.run(execution.execution_id)
    with pytest.raises(InvalidExecutionStateError, match="terminal"):
        engine.cancel(execution.execution_id)


def test_run_rejects_execution_id_collision_and_completed_task_cannot_dispatch_again() -> None:
    analyst = CountingAnalyst()
    engine = WorkflowEngine(agents=mock_agents(analyst=analyst))
    execution_id = uuid4()
    completed = engine.execute(definition(task("one")), execution_id=execution_id)

    with pytest.raises(InvalidExecutionStateError):
        engine.run(completed.execution_id)
    with pytest.raises(ValueError, match="already in use"):
        engine.create_execution(definition(task("one")), execution_id=execution_id)
    assert analyst.calls == 1


def test_workflow_task_error_exposes_aware_failure_timestamp() -> None:
    error = WorkflowTaskError(code="sample", message="Safe message.")

    assert error.occurred_at.tzinfo is not None
