import logging
import os

import pytest

os.environ["APP_ENV"] = "test"
os.environ["DATABASE_URL"] = "postgresql+psycopg://agentforge@localhost/agentforge"
os.environ["TEST_DATABASE_URL"] = "postgresql+psycopg://agentforge@localhost/agentforge_test"


@pytest.fixture(autouse=True)
def reset_workflow_logger_state() -> None:
    """Keep application logging configuration from leaking between test modules."""
    logger = logging.getLogger("agentforge.workflow.engine")
    logger.disabled = False
    logger.setLevel(logging.NOTSET)
    logger.propagate = True
