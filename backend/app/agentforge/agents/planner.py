"""Deterministic mock planner agent."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    AgentRole,
)
from agentforge.domain.agents.interface import Agent


class ProposedStep(BaseModel):
    """One draft step; it is not a validated or executable workflow step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_id: str = Field(min_length=1, max_length=64)
    assigned_role: AgentRole
    instruction: str = Field(min_length=1, max_length=10_000)


class PlannerResult(BaseModel):
    """Structured, explicitly non-executable mock planning output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    objective: str = Field(min_length=1, max_length=10_000)
    proposed_steps: list[ProposedStep] = Field(min_length=1)
    plan_status: str = "draft_only"


class PlannerAgent(Agent):
    """Turn a task into a fixed-shape draft without workflow validation."""

    IDENTITY: ClassVar[AgentIdentity] = AgentIdentity(
        agent_id="planner",
        name="Planner Agent",
        role=AgentRole.PLANNER,
        description="Creates a structured draft from the supplied task description.",
        supported_capabilities=frozenset({AgentCapability.CREATE_PLAN}),
    )

    @property
    def identity(self) -> AgentIdentity:
        return self.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutput:
        result = PlannerResult(
            objective=agent_input.task_description,
            proposed_steps=[
                ProposedStep(
                    step_id="draft-1",
                    assigned_role=AgentRole.ANALYST,
                    instruction=agent_input.task_description,
                )
            ],
        )
        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            result_data=result.model_dump(mode="json"),
            summary="Created a single-step draft; it has not been validated for execution.",
            metadata={"planning_mode": "deterministic_mock", "executable": False},
        )
