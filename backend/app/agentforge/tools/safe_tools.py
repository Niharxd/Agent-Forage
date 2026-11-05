"""Deterministic, dependency-free safe tools for local execution."""

from __future__ import annotations

from collections.abc import Mapping

from agentforge.domain.agents.contracts import AgentCapability
from agentforge.tools.contracts import ToolDefinition
from agentforge.tools.registry import ToolRegistry


def _validate_text_payload(payload: object) -> str:
    if not isinstance(payload, Mapping):
        raise ValueError("Expected an object containing a 'text' value.")
    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("Expected a string value for 'text'.")
    return text


def text_analysis_handler(payload: object) -> dict[str, object]:
    text = _validate_text_payload(payload)
    normalized = text
    char_count = len(normalized)
    lines = normalized.splitlines()
    line_count = len(lines) if normalized else 0
    words = normalized.split() if normalized else []
    return {
        "character_count": char_count,
        "word_count": len(words),
        "line_count": line_count,
        "empty": not bool(normalized.strip()),
        "preview": normalized[:80],
    }


def json_inspection_handler(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("Expected a JSON-compatible object.")
    data = payload.get("data")
    if data is None:
        raise ValueError("Expected a 'data' field containing a JSON-compatible value.")

    if isinstance(data, Mapping):
        top_level_keys = list(data.keys())
        value_types = {str(key): type(value).__name__ for key, value in data.items()}
        item_count = len(data)
    else:
        top_level_keys = []
        value_types = {}
        item_count = 0 if not isinstance(data, (list, tuple, set)) else len(data)
    return {
        "top_level_keys": top_level_keys,
        "value_types": value_types,
        "item_count": item_count,
        "type_name": type(data).__name__,
    }


def calculator_handler(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("Expected an object with operation and operands.")
    operation = payload.get("operation")
    left = payload.get("left")
    right = payload.get("right")
    if operation not in {
        "add",
        "addition",
        "+",
        "subtract",
        "subtraction",
        "-",
        "multiply",
        "*",
        "divide",
        "/",
    }:
        raise ValueError("Unsupported operation.")
    if not isinstance(left, (int, float)) or isinstance(left, bool):
        raise ValueError("left operand must be numeric.")
    if not isinstance(right, (int, float)) or isinstance(right, bool):
        raise ValueError("right operand must be numeric.")
    if operation in {"divide", "/"} and right == 0:
        raise ValueError("Division by zero is not allowed.")

    symbol = (
        operation
        if operation in {"+", "-", "*", "/"}
        else {
            "add": "+",
            "addition": "+",
            "subtract": "-",
            "subtraction": "-",
            "multiply": "*",
            "divide": "/",
        }[operation]
    )
    if operation in {"add", "addition", "+"}:
        result = left + right
    elif operation in {"subtract", "subtraction", "-"}:
        result = left - right
    elif operation in {"multiply", "*"}:
        result = left * right
    else:
        result = left / right
    return {"operation": symbol, "left": left, "right": right, "result": result}


TEXT_ANALYSIS_TOOL = ToolDefinition(
    tool_id="text_analysis",
    name="text_analysis",
    description="Count characters, words, and lines in supplied text.",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string", "maxLength": 10_000}},
        "required": ["text"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "character_count": {"type": "integer"},
            "word_count": {"type": "integer"},
            "line_count": {"type": "integer"},
            "empty": {"type": "boolean"},
            "preview": {"type": "string"},
        },
        "required": ["character_count", "word_count", "line_count", "empty", "preview"],
        "additionalProperties": False,
    },
    required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
    input_size_limit=10_000,
    output_size_limit=10_000,
    handler=text_analysis_handler,
)

JSON_INSPECTION_TOOL = ToolDefinition(
    tool_id="json_inspection",
    name="json_inspection",
    description="Inspect the keys, value types, and size of a JSON-compatible object.",
    input_schema={
        "type": "object",
        "properties": {"data": {"type": "object"}},
        "required": ["data"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "top_level_keys": {"type": "array"},
            "value_types": {"type": "object"},
            "item_count": {"type": "integer"},
            "type_name": {"type": "string"},
        },
        "required": ["top_level_keys", "value_types", "item_count", "type_name"],
        "additionalProperties": False,
    },
    required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
    handler=json_inspection_handler,
)

CALCULATOR_TOOL = ToolDefinition(
    tool_id="calculator",
    name="calculator",
    description="Perform a small set of safe arithmetic operations on numeric operands.",
    input_schema={
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": [
                    "add",
                    "addition",
                    "+",
                    "subtract",
                    "subtraction",
                    "-",
                    "multiply",
                    "*",
                    "divide",
                    "/",
                ],
            },
            "left": {"type": "number"},
            "right": {"type": "number"},
        },
        "required": ["operation", "left", "right"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "left": {"type": "number"},
            "right": {"type": "number"},
            "result": {"type": "number"},
        },
        "required": ["operation", "left", "right", "result"],
        "additionalProperties": False,
    },
    required_capabilities={AgentCapability.ANALYZE_SUPPLIED_DATA},
    handler=calculator_handler,
)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry([TEXT_ANALYSIS_TOOL, JSON_INSPECTION_TOOL, CALCULATOR_TOOL])


DEFAULT_TOOL_REGISTRY = create_default_registry()

__all__ = [
    "CALCULATOR_TOOL",
    "DEFAULT_TOOL_REGISTRY",
    "JSON_INSPECTION_TOOL",
    "TEXT_ANALYSIS_TOOL",
    "calculator_handler",
    "create_default_registry",
    "json_inspection_handler",
    "text_analysis_handler",
]
