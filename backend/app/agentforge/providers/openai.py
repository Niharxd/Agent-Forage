"""OpenAI Chat Completions adapter using the standard library HTTP client."""

import json
from http.client import HTTPException
from socket import timeout as SocketTimeout
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import SecretStr

from agentforge.domain.agents.contracts import AgentError, AgentErrorCode, JsonObject
from agentforge.providers.contracts import ProviderError

_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_MAX_RESPONSE_BYTES = 1_048_576
_MAX_COMPLETION_BYTES = 10_000


class OpenAIChatCompletionsProvider:
    """Request bounded JSON-object completions from the fixed OpenAI endpoint."""

    def __init__(
        self,
        *,
        api_key: SecretStr,
        model: str,
        timeout_seconds: float,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> JsonObject:
        request_body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0,
                "max_completion_tokens": 1200,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        request = Request(
            _ENDPOINT,
            data=request_body,
            headers={
                "Authorization": f"Bearer {self._api_key.get_secret_value()}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:
                body = response.read(_MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            exc.close()
            status = exc.code
            if status == 429:
                raise ProviderError(
                    AgentError(
                        code=AgentErrorCode.EXECUTION_FAILURE,
                        message="The OpenAI provider rate limit was reached.",
                        retryable=True,
                    )
                ) from exc
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.EXECUTION_FAILURE,
                    message="The OpenAI provider rejected the request.",
                    retryable=status >= 500,
                )
            ) from exc
        except (TimeoutError, SocketTimeout) as exc:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.TIMEOUT,
                    message="The OpenAI provider request timed out.",
                    retryable=True,
                )
            ) from exc
        except URLError as exc:
            is_timeout = isinstance(exc.reason, (TimeoutError, SocketTimeout))
            code = AgentErrorCode.TIMEOUT if is_timeout else AgentErrorCode.EXECUTION_FAILURE
            message = (
                "The OpenAI provider request timed out."
                if is_timeout
                else "The OpenAI provider request failed."
            )
            raise ProviderError(AgentError(code=code, message=message, retryable=True)) from exc
        except (OSError, HTTPException) as exc:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.EXECUTION_FAILURE,
                    message="The OpenAI provider request failed.",
                    retryable=True,
                )
            ) from exc

        if len(body) > _MAX_RESPONSE_BYTES:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider response exceeded the size limit.",
                )
            )
        try:
            response_data = json.loads(body)
            content = response_data["choices"][0]["message"]["content"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider returned an invalid response.",
                )
            ) from exc

        if not isinstance(content, str) or len(content.encode("utf-8")) > _MAX_COMPLETION_BYTES:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider completion exceeded the size limit.",
                )
            )
        try:
            completion = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider completion was not valid JSON.",
                )
            ) from exc
        if not isinstance(completion, dict):
            raise ProviderError(
                AgentError(
                    code=AgentErrorCode.VALIDATION_FAILURE,
                    message="The OpenAI provider completion must be a JSON object.",
                )
            )
        return completion
