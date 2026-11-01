"""Database engine and session factory construction."""

from sqlalchemy import create_engine as sqlalchemy_create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def create_database_engine(database_url: str) -> Engine:
    """Create a PostgreSQL engine with stale-connection checks enabled."""
    return sqlalchemy_create_engine(database_url, pool_pre_ping=True)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create sessions that leave transaction control to the caller."""
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
