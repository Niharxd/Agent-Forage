"""Deterministic mock researcher agent."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    AgentRole,
    JsonObject,
    PreviousAgentResult,
)
from agentforge.domain.agents.interface import Agent


class ResearcherResult(BaseModel):
    """Supplied material returned without adding external claims."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    supplied_information: JsonObject
    previous_results: list[PreviousAgentResult]
    findings: list[str] = Field(default_factory=list)
    external_research_performed: bool = False


class ResearcherAgent(Agent):
    """Report supplied information without network access or invented sources."""

    IDENTITY: ClassVar[AgentIdentity] = AgentIdentity(
        agent_id="researcher",
        name="Researcher Agent",
        role=AgentRole.RESEARCHER,
        description="Organizes supplied information without fetching external sources.",
        supported_capabilities=frozenset({AgentCapability.RESEARCH_SUPPLIED_INFORMATION}),
    )

    @property
    def identity(self) -> AgentIdentity:
        return self.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutput:
        result = ResearcherResult(
            supplied_information=agent_input.input_data,
            previous_results=agent_input.previous_results,
        )
        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            result_data=result.model_dump(mode="json"),
            summary="Returned only supplied information; no external research was performed.",
            metadata={"research_mode": "deterministic_mock", "network_access": False},
        )
