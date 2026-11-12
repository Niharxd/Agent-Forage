"""Registered tool interfaces, controlled execution, and safe local adapters."""

from agentforge.tools.contracts import (
    ToolDefinition,
    ToolExecutionError,
    ToolExecutionRequest,
    ToolExecutionResult,
    ToolExecutionStatus,
    ToolInput,
    ToolOutput,
)
from agentforge.tools.executor import ToolExecutionFailure, ToolExecutor
from agentforge.tools.registry import ToolRegistry
from agentforge.tools.safe_tools import (
    CALCULATOR_TOOL,
    DEFAULT_TOOL_REGISTRY,
    JSON_INSPECTION_TOOL,
    TEXT_ANALYSIS_TOOL,
    WIKIPEDIA_SEARCH_TOOL,
    calculator_handler,
    create_default_registry,
    json_inspection_handler,
    text_analysis_handler,
    wikipedia_search_handler,
)

__all__ = [
    "CALCULATOR_TOOL",
    "DEFAULT_TOOL_REGISTRY",
    "JSON_INSPECTION_TOOL",
    "TEXT_ANALYSIS_TOOL",
    "WIKIPEDIA_SEARCH_TOOL",
    "ToolDefinition",
    "ToolExecutionError",
    "ToolExecutionFailure",
    "ToolExecutionRequest",
    "ToolExecutionResult",
    "ToolExecutionStatus",
    "ToolExecutor",
    "ToolInput",
    "ToolOutput",
    "ToolRegistry",
    "calculator_handler",
    "create_default_registry",
    "json_inspection_handler",
    "text_analysis_handler",
    "wikipedia_search_handler",
]
