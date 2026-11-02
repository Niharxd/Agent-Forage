"""Deterministic mock reviewer agent."""

import json
from typing import ClassVar

from pydantic import BaseModel, ConfigDict

from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    AgentRole,
)
from agentforge.domain.agents.interface import Agent


class CriterionResult(BaseModel):
    """Result of a literal presence check against supplied review material."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criterion: str
    matched: bool


class ReviewerResult(BaseModel):
    """Review assessment limited to deterministic literal matching."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    criteria_results: list[CriterionResult]
    verdict: str
    evaluation_method: str = "literal_substring_mock"


class ReviewerAgent(Agent):
    """Check literal criterion presence without semantic quality judgments."""

    IDENTITY: ClassVar[AgentIdentity] = AgentIdentity(
        agent_id="reviewer",
        name="Reviewer Agent",
        role=AgentRole.REVIEWER,
        description="Checks supplied outputs against explicit criteria by literal match.",
        supported_capabilities=frozenset({AgentCapability.REVIEW_AGAINST_CRITERIA}),
    )

    @property
    def identity(self) -> AgentIdentity:
        return self.IDENTITY

    def _execute(self, agent_input: AgentInput) -> AgentOutput:
        material = json.dumps(
            {
                "input_data": agent_input.input_data,
                "previous_results": [
                    result.model_dump(mode="json") for result in agent_input.previous_results
                ],
            },
            sort_keys=True,
            ensure_ascii=True,
        ).casefold()
        criteria_results = [
            CriterionResult(criterion=criterion, matched=criterion.casefold() in material)
            for criterion in agent_input.review_criteria
        ]
        if not criteria_results:
            verdict = "not_evaluated"
        elif all(result.matched for result in criteria_results):
            verdict = "passed"
        else:
            verdict = "failed"

        result = ReviewerResult(
            criteria_results=criteria_results,
            verdict=verdict,
        )
        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            result_data=result.model_dump(mode="json"),
            summary="Checked literal text presence only; semantic quality was not evaluated.",
            metadata={"review_mode": "deterministic_mock"},
        )
