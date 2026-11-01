"""FastAPI database dependencies."""

from collections.abc import Generator

from fastapi import Request
from sqlalchemy.orm import Session


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Yield a request-scoped session and always close it after the response."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        raise RuntimeError("The database session factory has not been initialized")

    with session_factory() as session:
        yield session
