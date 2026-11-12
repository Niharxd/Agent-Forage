"""Provider-neutral structured completion contracts."""

from typing import Protocol

from agentforge.domain.agents.contracts import AgentError, JsonObject


class ProviderError(Exception):
    """A provider failure with a safe, provider-neutral agent error."""

    def __init__(self, error: AgentError) -> None:
        super().__init__(error.message)
        self.error = error


class StructuredOutputProvider(Protocol):
    """Generate a validated JSON object from bounded text prompts."""

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> JsonObject:
        """Return a structured completion or raise a safe ProviderError."""
