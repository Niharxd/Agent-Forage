"""Deterministic, dependency-free safe tools for local execution."""

from __future__ import annotations

import json
from collections.abc import Mapping
from ipaddress import ip_address
from json import JSONDecodeError
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from agentforge.domain.agents.contracts import AgentCapability
from agentforge.tools.contracts import ToolDefinition
from agentforge.tools.registry import ToolRegistry

_WIKIPEDIA_ENDPOINT = "https://en.wikipedia.org/w/api.php"
_WIKIPEDIA_HOST = "en.wikipedia.org"
_WIKIPEDIA_API_PATH = "/w/api.php"
_WIKIPEDIA_TIMEOUT_SECONDS = 8
_WIKIPEDIA_MAX_RESPONSE_BYTES = 256_000
_WIKIPEDIA_OUTPUT_BYTES = 5_000


class _WikipediaRedirectHandler(HTTPRedirectHandler):
    """Allow only HTTPS redirects to the configured Wikipedia API endpoint."""

    def redirect_request(
        self,
        request: Request,
        file: object,
        code: int,
        message: str,
        headers: object,
        new_url: str,
    ) -> Request | None:
        if request.get_method() != "GET":
            return None
        try:
            target = urlsplit(new_url)
            port = target.port
        except ValueError:
            return None

        hostname = target.hostname
        if hostname is None or hostname.casefold() != _WIKIPEDIA_HOST:
            return None
        try:
            ip_address(hostname)
        except ValueError:
            pass
        else:
            return None

        if (
            target.scheme != "https"
            or port not in {None, 443}
            or target.path != _WIKIPEDIA_API_PATH
            or target.username is not None
            or target.password is not None
            or target.fragment
        ):
            return None
        return super().redirect_request(request, file, code, message, headers, new_url)


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


def wikipedia_search_handler(payload: object) -> dict[str, object]:
    if not isinstance(payload, Mapping):
        raise ValueError("Expected an object containing a 'query' value.")
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip() or len(query.strip()) > 200:
        raise ValueError("The Wikipedia query must contain 1 to 200 characters.")
    query = query.strip()
    parameters = urlencode(
        {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrnamespace": 0,
            "gsrlimit": 5,
            "gsrsearch": query,
            "prop": "extracts",
            "exintro": 1,
            "explaintext": 1,
        }
    )
    request = Request(
        f"{_WIKIPEDIA_ENDPOINT}?{parameters}",
        headers={
            "User-Agent": "AgentForge/0.1 (https://github.com/Niharxd/Agent-Forage)",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        opener = build_opener(_WikipediaRedirectHandler())
        with opener.open(request, timeout=_WIKIPEDIA_TIMEOUT_SECONDS) as response:
            response_body = response.read(_WIKIPEDIA_MAX_RESPONSE_BYTES + 1)
    except TimeoutError:
        raise
    except HTTPError as exc:
        raise ValueError("Wikipedia search is temporarily unavailable.") from exc
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            raise TimeoutError("Wikipedia search timed out.") from exc
        raise ValueError("Wikipedia search is temporarily unavailable.") from exc
    except OSError as exc:
        raise ValueError("Wikipedia search is temporarily unavailable.") from exc

    if len(response_body) > _WIKIPEDIA_MAX_RESPONSE_BYTES:
        raise ValueError("Wikipedia returned a response that exceeded the size limit.")
    try:
        response_data = json.loads(response_body)
    except (JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("Wikipedia returned an invalid response.") from exc
    if not isinstance(response_data, dict) or not isinstance(response_data.get("query"), dict):
        raise ValueError("Wikipedia returned an invalid search result.")

    pages = response_data["query"].get("pages", {})
    if not isinstance(pages, dict):
        raise ValueError("Wikipedia returned an invalid search result.")

    results: list[dict[str, str]] = []
    for page in list(pages.values())[:5]:
        if not isinstance(page, dict):
            raise ValueError("Wikipedia returned an invalid search result.")
        title = page.get("title")
        extract = page.get("extract")
        page_id = page.get("pageid")
        if (
            not isinstance(title, str)
            or not isinstance(extract, str)
            or not isinstance(page_id, int)
            or isinstance(page_id, bool)
            or page_id < 1
        ):
            raise ValueError("Wikipedia returned an invalid search result.")
        excerpt = extract.strip()[:400]
        low = 0
        high = len(excerpt)
        bounded_result: dict[str, str] | None = None
        while low <= high:
            excerpt_length = (low + high) // 2
            candidate = {
                "title": title[:200],
                "url": f"https://en.wikipedia.org/?curid={page_id}",
                "extract": excerpt[:excerpt_length],
            }
            serialized = json.dumps(
                {"query": query, "results": [*results, candidate]},
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("utf-8")
            if len(serialized) <= _WIKIPEDIA_OUTPUT_BYTES:
                bounded_result = candidate
                low = excerpt_length + 1
            else:
                high = excerpt_length - 1
        if bounded_result is None or (excerpt and not bounded_result["extract"]):
            break
        results.append(bounded_result)
    return {"query": query, "results": results}


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

WIKIPEDIA_SEARCH_TOOL = ToolDefinition(
    tool_id="wikipedia_search",
    name="wikipedia_search",
    description=(
        "Search English Wikipedia for up to five brief, attributed excerpts. "
        "Sends only the supplied query to Wikipedia; performs read-only GET requests."
    ),
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string", "minLength": 1, "maxLength": 200}},
        "required": ["query"],
        "additionalProperties": False,
    },
    output_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "url": {"type": "string"},
                        "extract": {"type": "string"},
                    },
                    "required": ["title", "url", "extract"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["query", "results"],
        "additionalProperties": False,
    },
    required_capabilities={AgentCapability.RESEARCH_SUPPLIED_INFORMATION},
    input_size_limit=1_000,
    output_size_limit=_WIKIPEDIA_OUTPUT_BYTES,
    execution_limits={"timeout_ms": 8_000},
    handler=wikipedia_search_handler,
)


def create_default_registry() -> ToolRegistry:
    return ToolRegistry(
        [TEXT_ANALYSIS_TOOL, JSON_INSPECTION_TOOL, CALCULATOR_TOOL, WIKIPEDIA_SEARCH_TOOL]
    )


DEFAULT_TOOL_REGISTRY = create_default_registry()

__all__ = [
    "CALCULATOR_TOOL",
    "DEFAULT_TOOL_REGISTRY",
    "JSON_INSPECTION_TOOL",
    "TEXT_ANALYSIS_TOOL",
    "WIKIPEDIA_SEARCH_TOOL",
    "calculator_handler",
    "create_default_registry",
    "json_inspection_handler",
    "text_analysis_handler",
    "wikipedia_search_handler",
]
