import pytest
from agentforge.agents import (
    AnalystAgent,
    PlannerAgent,
    ResearcherAgent,
    ReviewerAgent,
)
from agentforge.domain.agents import (
    Agent,
    AgentError,
    AgentErrorCode,
    AgentExecutionError,
    AgentInput,
    AgentRole,
)
from agentforge.domain.agents.interface import AgentInputValue, AgentOutputValue
from agentforge.domain.workflows import (
    TaskStatus,
    WorkflowEventType,
    WorkflowStatus,
    WorkflowValidationError,
    WorkflowValidator,
)
from agentforge.workflow import WorkflowEngine


def task(
    task_id: str,
    agent_type: str = "analyst",
    dependency_ids: list[str] | None = None,
    **values: object,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "agent_type": agent_type,
        "dependency_ids": dependency_ids or [],
        **values,
    }


def workflow(*tasks: dict[str, object]) -> dict[str, object]:
    return {"name": "test workflow", "tasks": list(tasks)}


class RecordingAgent(Agent):
    def __init__(self, role: AgentRole, *, fail: bool = False) -> None:
        self._role = role
        self.fail = fail
        self.calls: list[AgentInput] = []
        self._implementation: Agent = {
            AgentRole.PLANNER: PlannerAgent(),
            AgentRole.RESEARCHER: ResearcherAgent(),
            AgentRole.ANALYST: AnalystAgent(),
            AgentRole.REVIEWER: ReviewerAgent(),
        }[role]

    @property
    def identity(self):
        return self._implementation.identity

    def execute(self, value: AgentInputValue):
        self.calls.append(AgentInput.model_validate(value))
        return super().execute(value)

    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        if self.fail:
            raise AgentExecutionError(
                AgentError(
                    code=AgentErrorCode.EXECUTION_FAILURE,
                    message="Controlled agent failure.",
                )
            )
        delegated_result = self._implementation.execute(agent_input)
        if delegated_result.error is not None:
            raise AgentExecutionError(delegated_result.error)
        return delegated_result.output.model_dump(mode="python")


def agents_with(**replacements: Agent) -> dict[AgentRole, Agent]:
    agents: dict[AgentRole, Agent] = {
        AgentRole.PLANNER: PlannerAgent(),
        AgentRole.RESEARCHER: ResearcherAgent(),
        AgentRole.ANALYST: AnalystAgent(),
        AgentRole.REVIEWER: ReviewerAgent(),
    }
    for role, agent in replacements.items():
        agents[AgentRole(role)] = agent
    return agents


def issue_codes(error: WorkflowValidationError) -> set[str]:
    return {issue.code for issue in error.issues}


def test_validator_accepts_valid_workflow() -> None:
    definition = workflow(
        task("research", "researcher"), task("analysis", dependency_ids=["research"])
    )

    validated = WorkflowValidator().validate(definition)

    assert validated.name == "test workflow"
    assert len(validated.tasks) == 2


def test_validator_rejects_empty_workflow() -> None:
    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate({"tasks": []})

    assert error.value.issues[0].code == "too_short"


def test_validator_rejects_duplicate_task_ids() -> None:
    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(workflow(task("same"), task("same")))

    assert "duplicate_task_id" in issue_codes(error.value)


def test_validator_rejects_missing_dependency() -> None:
    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(workflow(task("task-a", dependency_ids=["missing"])))

    assert "missing_dependency" in issue_codes(error.value)


def test_validator_rejects_self_dependency() -> None:
    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(workflow(task("task-a", dependency_ids=["task-a"])))

    assert "self_dependency" in issue_codes(error.value)


def test_validator_rejects_cycles() -> None:
    definition = workflow(
        task("task-a", dependency_ids=["task-b"]),
        task("task-b", dependency_ids=["task-a"]),
    )

    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(definition)

    assert "circular_dependency" in issue_codes(error.value)


def test_validator_rejects_invalid_agent_type() -> None:
    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(workflow(task("task-a", "unknown")))

    assert error.value.issues[0].code == "enum"


def test_validator_enforces_configured_and_default_task_limits() -> None:
    definition = workflow(task("a"), task("b"), task("c"))

    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator(max_tasks=2).validate(definition)

    assert "maximum_task_limit" in issue_codes(error.value)
    WorkflowValidator().validate(workflow(*(task(str(index)) for index in range(25))))
    with pytest.raises(WorkflowValidationError) as default_limit_error:
        WorkflowValidator().validate(workflow(*(task(str(index)) for index in range(26))))
    assert "maximum_task_limit" in issue_codes(default_limit_error.value)
    with pytest.raises(ValueError):
        WorkflowValidator(max_tasks=26)


def test_validator_rejects_duplicate_dependencies() -> None:
    definition = workflow(task("parent"), task("child", dependency_ids=["parent", "parent"]))

    with pytest.raises(WorkflowValidationError) as error:
        WorkflowValidator().validate(definition)

    assert "duplicate_dependency" in issue_codes(error.value)


def test_validator_rechecks_mutated_pydantic_workflow_instances() -> None:
    definition = WorkflowValidator().validate(workflow(task("valid")))
    definition.tasks[0].agent_type = "invalid"

    with pytest.raises(WorkflowValidationError):
        WorkflowValidator().validate(definition)


def test_dependency_order_is_sequential_and_respects_dependencies() -> None:
    definition = workflow(
        task("third", dependency_ids=["second"]),
        task("first"),
        task("second", dependency_ids=["first"]),
    )

    ordered = WorkflowValidator().topological_order(definition)

    assert [item.task_id for item in ordered] == ["first", "second", "third"]


def test_independent_tasks_have_stable_lexical_order() -> None:
    definition = workflow(task("zebra"), task("alpha"), task("middle"))

    first_order = WorkflowValidator().topological_order(definition)
    second_order = WorkflowValidator().topological_order(definition)

    assert [item.task_id for item in first_order] == ["alpha", "middle", "zebra"]
    assert [item.task_id for item in second_order] == [item.task_id for item in first_order]


def test_multiple_dependencies_resolve_after_each_parent() -> None:
    definition = workflow(
        task("final", dependency_ids=["right", "left"]),
        task("right"),
        task("left"),
    )

    ordered = WorkflowValidator().topological_order(definition)

    assert [item.task_id for item in ordered] == ["left", "right", "final"]


def test_dependency_order_rejects_cycle() -> None:
    definition = workflow(
        task("a", dependency_ids=["b"]),
        task("b", dependency_ids=["a"]),
    )

    with pytest.raises(WorkflowValidationError, match="directed acyclic graph"):
        WorkflowValidator().topological_order(definition)


def test_engine_executes_dependencies_and_dispatches_to_designated_agents() -> None:
    researcher = RecordingAgent(AgentRole.RESEARCHER)
    analyst = RecordingAgent(AgentRole.ANALYST)
    definition = workflow(
        task(
            "analysis",
            "analyst",
            dependency_ids=["research"],
            description="Analyze prior result",
            input_data={"numbers": [1, 2]},
        ),
        task("research", "researcher", description="Organize supplied notes"),
    )

    result = WorkflowEngine(agents=agents_with(researcher=researcher, analyst=analyst)).execute(
        definition
    )

    assert result.status == WorkflowStatus.COMPLETED
    assert result.task_results["research"].agent_result.output.agent_id == "researcher"
    assert result.task_results["analysis"].agent_result.output.agent_id == "analyst"
    assert len(analyst.calls[0].previous_results) == 1
    assert analyst.calls[0].previous_results[0].agent_id == "researcher"
    assert analyst.calls[0].task_description == "Analyze prior result"
    assert [
        event.task_id
        for event in result.events
        if event.event_type == WorkflowEventType.TASK_STARTED
    ] == [
        "research",
        "analysis",
    ]


def test_engine_runs_all_four_registered_mock_agents() -> None:
    definition = workflow(
        task("planner", "planner"),
        task("researcher", "researcher"),
        task("analyst", "analyst"),
        task("reviewer", "reviewer", review_criteria=["marker"]),
    )

    result = WorkflowEngine().execute(definition)

    assert result.status == WorkflowStatus.COMPLETED
    assert {
        task_result.agent_result.output.agent_id for task_result in result.task_results.values()
    } == {"planner", "researcher", "analyst", "reviewer"}


def test_failure_blocks_dependents_but_independent_tasks_continue() -> None:
    failing_researcher = RecordingAgent(AgentRole.RESEARCHER, fail=True)
    analyst = RecordingAgent(AgentRole.ANALYST)
    definition = workflow(
        task("a-fail", "researcher"),
        task("b-dependent", dependency_ids=["a-fail"]),
        task("c-independent"),
        task("d-transitive", dependency_ids=["b-dependent"]),
    )

    result = WorkflowEngine(
        agents=agents_with(researcher=failing_researcher, analyst=analyst)
    ).execute(definition)

    assert result.status == WorkflowStatus.FAILED
    assert result.task_results["a-fail"].status == TaskStatus.FAILED
    assert result.task_results["a-fail"].error.code == "execution_failure"
    assert result.task_results["b-dependent"].status == TaskStatus.BLOCKED
    assert result.task_results["d-transitive"].status == TaskStatus.BLOCKED
    assert result.task_results["c-independent"].status == TaskStatus.COMPLETED
    assert len(failing_researcher.calls) == 1
    assert len(analyst.calls) == 1
    assert analyst.calls[0].execution_context["task_id"] == "c-independent"
    assert WorkflowEventType.TASK_FAILED in [event.event_type for event in result.events]
    blocked_events = [
        event for event in result.events if event.event_type == WorkflowEventType.TASK_BLOCKED
    ]
    assert [event.task_id for event in blocked_events] == ["b-dependent", "d-transitive"]
    assert result.events[-1].event_type == WorkflowEventType.WORKFLOW_FAILED


def test_successful_execution_emits_lifecycle_events_and_timestamps() -> None:
    result = WorkflowEngine().execute(workflow(task("one")))
    event_types = [event.event_type for event in result.events]

    assert result.status == WorkflowStatus.COMPLETED
    assert event_types == [
        WorkflowEventType.WORKFLOW_STARTED,
        WorkflowEventType.TASK_STARTED,
        WorkflowEventType.TASK_COMPLETED,
        WorkflowEventType.WORKFLOW_COMPLETED,
    ]
    assert result.started_at is not None
    assert result.completed_at is not None
    assert result.events[0].timestamp.tzinfo is not None
    assert result.events[0].occurred_at == result.events[0].timestamp
    assert result.events[1].details["task_id"] == "one"


def test_invalid_workflow_is_rejected_before_agent_invocation() -> None:
    researcher = RecordingAgent(AgentRole.RESEARCHER)
    definition = workflow(
        task("one", "researcher", dependency_ids=["missing"]),
    )

    with pytest.raises(WorkflowValidationError):
        WorkflowEngine(agents=agents_with(researcher=researcher)).execute(definition)

    assert researcher.calls == []


def test_unexpected_agent_exception_is_recorded_and_execution_continues() -> None:
    class RaisingAgent(RecordingAgent):
        def execute(self, value: AgentInputValue):
            self.calls.append(AgentInput.model_validate(value))
            raise OSError("private diagnostic detail")

    raising = RaisingAgent(AgentRole.RESEARCHER)
    definition = workflow(task("a-error", "researcher"), task("b-independent"))
    result = WorkflowEngine(agents=agents_with(researcher=raising)).execute(definition)

    assert result.status == WorkflowStatus.FAILED
    assert result.task_results["a-error"].error.code == "agent_exception"
    assert result.task_results["a-error"].error.details == {"exception_type": "OSError"}
    assert result.task_results["b-independent"].status == TaskStatus.COMPLETED
    failure_event = next(
        event for event in result.events if event.event_type == WorkflowEventType.TASK_FAILED
    )
    assert failure_event.metadata["error"]["code"] == "agent_exception"


def test_execution_id_can_be_supplied() -> None:
    from uuid import UUID

    execution_id = UUID("a7a60f6a-6a91-4312-9462-e7b3db790941")
    result = WorkflowEngine().execute(workflow(task("one")), execution_id=execution_id)

    assert result.execution_id == execution_id
    assert all(event.execution_id == execution_id for event in result.events)


def test_agent_registry_rejects_mismatched_role() -> None:
    with pytest.raises(ValueError, match="does not match"):
        WorkflowEngine(agents=agents_with(researcher=PlannerAgent()))
