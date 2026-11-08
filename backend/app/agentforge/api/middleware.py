"""HTTP middleware for bounded API request bodies."""

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from agentforge.api.errors import error_content


class RequestSizeLimitMiddleware:
    """Reject request bodies above a fixed bound before JSON parsing."""

    def __init__(self, app: ASGIApp, max_bytes: int = 1_048_576) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] in {"GET", "HEAD", "OPTIONS"}:
            await self.app(scope, receive, send)
            return

        chunks = bytearray()
        while True:
            message = await receive()
            if message["type"] != "http.request":
                if message["type"] == "http.disconnect":
                    return
                continue
            chunks.extend(message.get("body", b""))
            if len(chunks) > self.max_bytes:
                response = JSONResponse(
                    status_code=413,
                    content=error_content(
                        "request_too_large",
                        "The request body exceeds the allowed size.",
                    ),
                )
                await response(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        body = bytes(chunks)
        replayed = False

        async def replay_body() -> Message:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        await self.app(scope, replay_body, send)
