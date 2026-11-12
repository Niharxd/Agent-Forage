"""Optional shared-token authentication for provider-enabled API access."""

import hmac

from fastapi import HTTPException, Request


def require_api_access_token(request: Request) -> None:
    """Require the configured bearer token on protected API routers."""
    settings = request.app.state.settings
    expected_token = settings.api_access_token
    if expected_token is None:
        raise RuntimeError("API access token is not configured for protected routes.")

    authorization = request.headers.get("authorization", "")
    scheme, separator, supplied_token = authorization.partition(" ")
    if (
        not separator
        or scheme.casefold() != "bearer"
        or not supplied_token
        or not hmac.compare_digest(supplied_token, expected_token.get_secret_value())
    ):
        raise HTTPException(
            status_code=401,
            detail="Authentication is required.",
            headers={"WWW-Authenticate": "Bearer"},
        )
