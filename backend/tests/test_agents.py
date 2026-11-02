from collections.abc import Mapping

import pytest
from agentforge.agents import AnalystAgent, PlannerAgent, ResearcherAgent, ReviewerAgent
from agentforge.domain.agents import (
    Agent,
    AgentCapability,
    AgentError,
    AgentErrorCode,
    AgentExecutionError,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    AgentRole,
)
from agentforge.domain.agents.interface import AgentOutputValue
from pydantic import ValidationError

AGENTS = [PlannerAgent(), ResearcherAgent(), AnalystAgent(), ReviewerAgent()]


@pytest.mark.parametrize(
    ("agent_id", "role", "capability"),
    [
        ("planner", AgentRole.PLANNER, AgentCapability.CREATE_PLAN),
        (
            "researcher",
            AgentRole.RESEARCHER,
            AgentCapability.RESEARCH_SUPPLIED_INFORMATION,
        ),
        ("analyst", AgentRole.ANALYST, AgentCapability.ANALYZE_SUPPLIED_DATA),
        ("reviewer", AgentRole.REVIEWER, AgentCapability.REVIEW_AGAINST_CRITERIA),
    ],
)
def test_agent_identities_are_valid_and_match_supported_roles(
    agent_id: str,
    role: AgentRole,
    capability: AgentCapability,
) -> None:
    agent = next(agent for agent in AGENTS if agent.identity.agent_id == agent_id)

    assert agent.identity.role == role
    assert agent.identity.version == "1.0.0"
    assert agent.supported_capabilities == frozenset({capability})


@pytest.mark.parametrize(
    "identity_values",
    [
        {
            "agent_id": "Planner",
            "name": "Planner",
            "role": "planner",
            "description": "Makes plans",
            "supported_capabilities": ["create_plan"],
        },
        {
            "agent_id": "planner",
            "name": "",
            "role": "planner",
            "description": "Makes plans",
            "supported_capabilities": ["create_plan"],
        },
        {
            "agent_id": "planner",
            "name": "Planner",
            "role": "unknown",
            "description": "Makes plans",
            "supported_capabilities": ["create_plan"],
        },
        {
            "agent_id": "planner",
            "name": "Planner",
            "role": "planner",
            "description": "Makes plans",
            "supported_capabilities": ["unknown"],
        },
        {
            "agent_id": "planner",
            "name": "Planner",
            "role": "planner",
            "description": "Makes plans",
            "supported_capabilities": ["create_plan"],
            "version": "latest",
        },
    ],
)
def test_invalid_agent_identities_are_rejected(identity_values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentIdentity.model_validate(identity_values)


def test_agent_input_accepts_context_data_and_previous_results() -> None:
    agent_input = AgentInput(
        task_description="  Summarize the supplied report  ",
        execution_context={"workflow_id": "wf-1"},
        input_data={"report": {"title": "Quarterly results"}},
        previous_results=[
            {
                "agent_id": "researcher",
                "status": "succeeded",
                "result_data": {"finding": "Revenue increased"},
                "summary": "Returned supplied finding.",
            }
        ],
        metadata={"request_id": "request-1"},
        review_criteria=["Revenue increased"],
    )

    assert agent_input.task_description == "Summarize the supplied report"
    assert agent_input.previous_results[0].agent_id == "researcher"


@pytest.mark.parametrize(
    "input_values",
    [
        {},
        {"task_description": ""},
        {"task_description": "  "},
        {"task_description": "x" * 10_001},
        {"task_description": "valid", "input_data": {"bad": object()}},
        {"task_description": "valid", "unexpected": True},
        {"task_description": "valid", "review_criteria": ["  "]},
    ],
)
def test_invalid_or_incomplete_agent_inputs_are_rejected(
    input_values: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AgentInput.model_validate(input_values)


def test_valid_agent_output_and_execution_result() -> None:
    output = AgentOutput(
        agent_id="planner",
        status=AgentExecutionStatus.SUCCEEDED,
        result_data={"steps": [{"id": "draft-1"}]},
        summary="Created a draft.",
        metadata={"executable": False},
    )
    result = AgentExecutionResult(
        status=AgentExecutionStatus.SUCCEEDED,
        output=output,
        execution_duration_ms=12,
    )

    assert result.output.result_data["steps"] == [{"id": "draft-1"}]
    assert result.token_usage is None


@pytest.mark.parametrize(
    "output_values",
    [
        {"agent_id": "planner", "status": "failed", "summary": "No error provided."},
        {
            "agent_id": "planner",
            "status": "succeeded",
            "summary": "Invalid token count.",
            "result_data": {"count": object()},
        },
        {
            "agent_id": "planner",
            "status": "succeeded",
            "summary": "Should not contain an error.",
            "error": {"code": "execution_failure", "message": "failed"},
        },
    ],
)
def test_invalid_agent_outputs_are_rejected(output_values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        AgentOutput.model_validate(output_values)


@pytest.mark.parametrize("error_code", list(AgentErrorCode))
def test_error_categories_have_consistent_structured_representations(
    error_code: AgentErrorCode,
) -> None:
    error = AgentError(code=error_code, message="A deterministic test error.")

    assert error.code == error_code
    assert error.retryable is False
    assert error.details == {}


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.identity.agent_id)
def test_all_agents_execute_with_consistent_success_contract(agent: Agent) -> None:
    result = agent.execute(
        AgentInput(
            task_description="Process the supplied material.",
            input_data={"sample": ["one", "two"]},
            requested_capabilities=agent.supported_capabilities,
        )
    )

    assert result.status == AgentExecutionStatus.SUCCEEDED
    assert result.output.agent_id == agent.identity.agent_id
    assert result.output.status == AgentExecutionStatus.SUCCEEDED
    assert result.output.summary
    assert result.execution_duration_ms >= 0
    assert result.token_usage is None


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.identity.agent_id)
def test_invalid_input_returns_classified_failure(agent: Agent) -> None:
    result = agent.execute({"task_description": ""})

    assert result.status == AgentExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == AgentErrorCode.INVALID_INPUT
    assert result.output.error == result.error


@pytest.mark.parametrize("agent", AGENTS, ids=lambda agent: agent.identity.agent_id)
def test_unsupported_capability_returns_classified_failure(agent: Agent) -> None:
    unsupported = (
        AgentCapability.CREATE_PLAN
        if AgentCapability.CREATE_PLAN not in agent.supported_capabilities
        else AgentCapability.ANALYZE_SUPPLIED_DATA
    )
    result = agent.execute(
        AgentInput(
            task_description="Request a capability.",
            requested_capabilities=frozenset({unsupported}),
        )
    )

    assert result.status == AgentExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == AgentErrorCode.UNSUPPORTED_CAPABILITY
    assert result.error.details["unsupported_capabilities"] == [unsupported.value]


def test_planner_returns_a_draft_not_an_executable_plan() -> None:
    result = PlannerAgent().execute({"task_description": "Inspect the supplied dataset."})

    assert result.output.result_data["plan_status"] == "draft_only"
    assert result.output.metadata["executable"] is False
    assert result.output.result_data["proposed_steps"][0]["instruction"] == (
        "Inspect the supplied dataset."
    )


def test_researcher_does_not_add_external_information() -> None:
    result = ResearcherAgent().execute(
        {
            "task_description": "Research the supplied notes.",
            "input_data": {"notes": "Known fact from the user."},
        }
    )

    assert result.output.result_data["supplied_information"] == {
        "notes": "Known fact from the user."
    }
    assert result.output.result_data["findings"] == []
    assert result.output.result_data["external_research_performed"] is False


def test_analyst_reports_supplied_data_types_deterministically() -> None:
    result = AnalystAgent().execute(
        {
            "task_description": "Analyze these values.",
            "input_data": {"count": 2, "enabled": True, "labels": ["a"]},
        }
    )

    assert result.output.result_data["observations"] == [
        {"field": "count", "value_type": "integer"},
        {"field": "enabled", "value_type": "boolean"},
        {"field": "labels", "value_type": "array"},
    ]


def test_reviewer_checks_only_literal_criterion_presence() -> None:
    result = ReviewerAgent().execute(
        {
            "task_description": "Review the previous result.",
            "previous_results": [
                {
                    "agent_id": "analyst",
                    "status": "succeeded",
                    "result_data": {"finding": "Revenue increased"},
                    "summary": "A supplied result.",
                }
            ],
            "review_criteria": ["Revenue increased", "source citation"],
        }
    )

    assert result.output.result_data["verdict"] == "failed"
    assert result.output.result_data["criteria_results"] == [
        {"criterion": "Revenue increased", "matched": True},
        {"criterion": "source citation", "matched": False},
    ]


class FailingAgent(Agent):
    @property
    def identity(self) -> AgentIdentity:
        return PlannerAgent.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        raise AgentExecutionError(
            AgentError(
                code=AgentErrorCode.TIMEOUT,
                message="The deterministic mock timed out.",
                retryable=True,
            )
        )


class ExecutionFailureAgent(Agent):
    @property
    def identity(self) -> AgentIdentity:
        return PlannerAgent.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        raise AgentExecutionError(
            AgentError(
                code=AgentErrorCode.EXECUTION_FAILURE,
                message="The deterministic mock failed.",
            )
        )


class InvalidOutputAgent(Agent):
    @property
    def identity(self) -> AgentIdentity:
        return PlannerAgent.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        return {"agent_id": self.identity.agent_id, "status": "succeeded"}


@pytest.mark.parametrize(
    ("agent", "expected_code"),
    [
        (FailingAgent(), AgentErrorCode.TIMEOUT),
        (ExecutionFailureAgent(), AgentErrorCode.EXECUTION_FAILURE),
        (InvalidOutputAgent(), AgentErrorCode.VALIDATION_FAILURE),
    ],
)
def test_execution_failures_are_reported_without_success_shaped_fallbacks(
    agent: Agent,
    expected_code: AgentErrorCode,
) -> None:
    result = agent.execute(AgentInput(task_description="Run a failure scenario."))

    assert result.status == AgentExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == expected_code
    assert result.output.status == AgentExecutionStatus.FAILED


def test_output_from_different_agent_is_a_validation_failure() -> None:
    class WrongIdentityAgent(Agent):
        @property
        def identity(self) -> AgentIdentity:
            return PlannerAgent.IDENTITY

        def _execute(self, agent_input: AgentInput) -> Mapping[str, object]:
            return AgentOutput(
                agent_id="analyst",
                status=AgentExecutionStatus.SUCCEEDED,
                summary="Wrong identity.",
            ).model_dump(mode="json")

    result = WrongIdentityAgent().execute(AgentInput(task_description="Check identity."))

    assert result.status == AgentExecutionStatus.FAILED
    assert result.error is not None
    assert result.error.code == AgentErrorCode.VALIDATION_FAILURE
