"""Provider-independent interface and shared execution behavior for agents."""

from abc import ABC, abstractmethod
from collections.abc import Mapping
from time import perf_counter
from typing import TypeAlias

from pydantic import ValidationError

from agentforge.domain.agents.contracts import (
    AgentCapability,
    AgentError,
    AgentErrorCode,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentIdentity,
    AgentInput,
    AgentOutput,
    JsonObject,
)

AgentInputValue: TypeAlias = AgentInput | Mapping[str, object]
AgentOutputValue: TypeAlias = AgentOutput | Mapping[str, object]


class AgentExecutionError(Exception):
    """A classified failure raised by an agent implementation."""

    def __init__(self, error: AgentError) -> None:
        super().__init__(error.message)
        self.error = error


class Agent(ABC):
    """Simple synchronous contract implemented by every specialized agent."""

    @property
    @abstractmethod
    def identity(self) -> AgentIdentity:
        """Return this implementation's stable identity and declared metadata."""

    @property
    def supported_capabilities(self) -> frozenset[AgentCapability]:
        """Expose capabilities from the identity as the runtime allowlist."""
        return self.identity.supported_capabilities

    def validate_input(self, value: AgentInputValue) -> AgentInput:
        """Validate raw input into the common provider-neutral input contract."""
        return AgentInput.model_validate(value)

    def execute(self, value: AgentInputValue) -> AgentExecutionResult:
        """Validate, execute, and normalize an agent invocation."""
        started_at = perf_counter()
        try:
            agent_input = self.validate_input(value)
        except ValidationError as exc:
            return self._failure(
                self._validation_error(AgentErrorCode.INVALID_INPUT, exc),
                started_at,
            )

        unsupported = agent_input.requested_capabilities - self.supported_capabilities
        if unsupported:
            names = sorted(capability.value for capability in unsupported)
            return self._failure(
                AgentError(
                    code=AgentErrorCode.UNSUPPORTED_CAPABILITY,
                    message=f"{self.identity.name} does not support the requested capability.",
                    details={"unsupported_capabilities": names},
                ),
                started_at,
            )

        try:
            output = AgentOutput.model_validate(self._execute(agent_input))
        except AgentExecutionError as exc:
            return self._failure(exc.error, started_at)
        except ValidationError as exc:
            return self._failure(
                self._validation_error(AgentErrorCode.VALIDATION_FAILURE, exc),
                started_at,
            )

        if output.agent_id != self.identity.agent_id:
            return self._failure(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="Agent output identity does not match the executing agent.",
                ),
                started_at,
            )

        return AgentExecutionResult(
            status=output.status,
            output=output,
            execution_duration_ms=self._duration_ms(started_at),
            error=output.error,
            metadata={"execution_mode": "deterministic_mock"},
        )

    @abstractmethod
    def _execute(self, agent_input: AgentInput) -> AgentOutputValue:
        """Produce a validated agent output from validated input."""

    def _failure(self, error: AgentError, started_at: float) -> AgentExecutionResult:
        output = AgentOutput(
            agent_id=self.identity.agent_id,
            status=AgentExecutionStatus.FAILED,
            summary=f"{self.identity.name} could not complete the request: {error.message}",
            error=error,
        )
        return AgentExecutionResult(
            status=AgentExecutionStatus.FAILED,
            output=output,
            execution_duration_ms=self._duration_ms(started_at),
            error=error,
            metadata={"execution_mode": "deterministic_mock"},
        )

    @staticmethod
    def _duration_ms(started_at: float) -> int:
        return max(0, round((perf_counter() - started_at) * 1000))

    @staticmethod
    def _validation_error(code: AgentErrorCode, error: ValidationError) -> AgentError:
        issues = [
            {
                "location": ".".join(str(part) for part in issue["loc"]),
                "type": issue["type"],
                "message": issue["msg"],
            }
            for issue in error.errors(include_url=False, include_context=False, include_input=False)
        ]
        message = (
            "Agent input validation failed."
            if code == AgentErrorCode.INVALID_INPUT
            else "Agent output validation failed."
        )
        details: JsonObject = {"issues": issues}
        return AgentError(code=code, message=message, details=details)
