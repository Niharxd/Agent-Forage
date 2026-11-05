"""Registry for approved, capability-scoped tool definitions."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from agentforge.domain.agents.contracts import AgentCapability
from agentforge.tools.contracts import ToolDefinition


class ToolRegistry:
    """In-memory registry of trusted tool definitions and metadata."""

    def __init__(self, tools: Iterable[ToolDefinition] | None = None) -> None:
        self._tools: dict[str, ToolDefinition] = {}
        self._names: dict[str, ToolDefinition] = {}
        if tools:
            for tool in tools:
                self.register(tool)

    def register(self, tool: ToolDefinition) -> ToolDefinition:
        """Register a new tool definition. Duplicate IDs and names are rejected."""
        if tool.tool_id in self._tools:
            raise ValueError(f"Tool {tool.tool_id!r} is already registered.")
        normalized_name = tool.name.casefold()
        if normalized_name in self._names:
            raise ValueError(f"Tool name {tool.name!r} is already registered.")
        self._tools[tool.tool_id] = tool
        self._names[normalized_name] = tool
        return tool

    def get_by_id(self, tool_id: str) -> ToolDefinition | None:
        return self._tools.get(tool_id)

    def get_by_name(self, name: str) -> ToolDefinition | None:
        return self._names.get(name.casefold())

    def list_tools(self) -> tuple[ToolDefinition, ...]:
        """Return an immutable snapshot of the registry contents."""
        return tuple(self._tools.values())

    def list_tools_for_capability(
        self, capability: AgentCapability | str
    ) -> tuple[ToolDefinition, ...]:
        required = AgentCapability(capability)
        return tuple(
            tool for tool in self._tools.values() if required in tool.required_capabilities
        )

    def disable_tool(self, tool_id: str) -> ToolDefinition:
        tool = self.get_by_id(tool_id)
        if tool is None:
            raise KeyError(f"Tool {tool_id!r} is not registered.")
        updated = tool.model_copy(update={"enabled": False})
        self._tools[tool_id] = updated
        self._names[tool.name.casefold()] = updated
        return updated

    def enable_tool(self, tool_id: str) -> ToolDefinition:
        tool = self.get_by_id(tool_id)
        if tool is None:
            raise KeyError(f"Tool {tool_id!r} is not registered.")
        updated = tool.model_copy(update={"enabled": True})
        self._tools[tool_id] = updated
        self._names[tool.name.casefold()] = updated
        return updated

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, tool_id: str) -> bool:
        return tool_id in self._tools

    def snapshot(self) -> Mapping[str, ToolDefinition]:
        """Expose a read-only registry snapshot without mutable state."""
        return dict(self._tools)
