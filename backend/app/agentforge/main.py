"""FastAPI application entry point."""

import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from agentforge.api.errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from agentforge.api.routes.health import router as health_router
from agentforge.config.settings import Settings


def configure_logging(log_level: str) -> None:
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    logging.getLogger().setLevel(log_level)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the API application with explicit runtime settings."""
    app_settings = settings or Settings()
    configure_logging(app_settings.log_level)

    application = FastAPI(
        title="AgentForge API",
        version="1.0.0",
    )
    application.add_middleware(
        CORSMiddleware,
        allow_origins=app_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["*"],
    )
    application.add_exception_handler(StarletteHTTPException, http_exception_handler)
    application.add_exception_handler(RequestValidationError, validation_exception_handler)
    application.add_exception_handler(Exception, unhandled_exception_handler)
    application.include_router(health_router, prefix="/api/v1")
    return application


app = create_app()
