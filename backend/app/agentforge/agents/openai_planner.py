"""Planner agent backed by the configured structured-output provider."""

from pydantic import ValidationError

from agentforge.agents.planner import PlannerAgent, PlannerResult
from agentforge.domain.agents.contracts import (
    AgentError,
    AgentErrorCode,
    AgentExecutionStatus,
    AgentInput,
    AgentOutput,
)
from agentforge.domain.agents.interface import AgentExecutionError
from agentforge.providers.contracts import ProviderError, StructuredOutputProvider

_SYSTEM_PROMPT = (
    "Create a draft workflow for the supplied task. Return a JSON object with exactly "
    "these fields: objective, proposed_steps, plan_status. Each proposed_steps item must "
    "contain exactly step_id, assigned_role, and instruction. Use only planner, researcher, "
    "analyst, or reviewer roles. Return 1 to 25 steps. Do not request tools, execute work, "
    "or claim the plan is executable. Set plan_status to draft_only."
)


class OpenAIPlannerAgent(PlannerAgent):
    """Create a validated, non-executable plan with a structured-output provider."""

    def __init__(self, provider: StructuredOutputProvider) -> None:
        self._provider = provider

    @property
    def execution_mode(self) -> str:
        return "openai"

    def _execute(self, agent_input: AgentInput) -> AgentOutput:
        try:
            proposed = self._provider.generate_json(
                system_prompt=_SYSTEM_PROMPT,
                user_prompt=agent_input.task_description,
            )
        except ProviderError as exc:
            raise AgentExecutionError(exc.error) from exc

        try:
            plan = PlannerResult.model_validate(proposed)
        except ValidationError as exc:
            raise AgentExecutionError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider returned an invalid workflow draft.",
                )
            ) from exc

        return AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.SUCCEEDED,
            result_data=plan.model_dump(mode="json"),
            summary="Created a draft workflow; it has not been validated or executed.",
            metadata={"planning_mode": "openai", "executable": False},
        )
