"""Deterministic mock analyst agent."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    AgentRole,
    JsonValue,
)
from agentforge.domain.agents.interface import Agent


class DataObservation(BaseModel):
    """A top-level field and its JSON value type."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field: str
    value_type: str


class AnalystResult(BaseModel):
    """A deterministic description of supplied data structure."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observations: list[DataObservation]
    previous_result_count: int
    analysis_method: str = "top_level_structure_only"


class AnalystAgent(Agent):
    """Describe the shape of supplied data without external facts or inference."""

    IDENTITY: ClassVar[AgentIdentity] = AgentIdentity(
        agent_id="analyst",
        name="Analyst Agent",
        role=AgentRole.ANALYST,
        description="Reports the top-level structure and JSON types of supplied data.",
        supported_capabilities=frozenset({AgentCapability.ANALYZE_SUPPLIED_DATA}),
    )

    @property
    def identity(self) -> AgentIdentity:
        return self.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutput:
        result = AnalystResult(
            observations=[
                DataObservation(field=field, value_type=self._json_type(value))
                for field, value in sorted(agent_input.input_data.items())
            ],
            previous_result_count=len(agent_input.previous_results),
        )
        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            result_data=result.model_dump(mode="json"),
            summary="Described supplied data structure only; no external facts were introduced.",
            metadata={"analysis_mode": "deterministic_mock"},
        )

    @staticmethod
    def _json_type(value: JsonValue) -> str:
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        if isinstance(value, str):
            return "string"
        if isinstance(value, list):
            return "array"
        return "object"
