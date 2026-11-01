"""Versioned workflow persistence model."""

from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.database.base import Base
from agentforge.domain.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from agentforge.domain.models.execution import WorkflowExecution


class Workflow(TimestampMixin, Base):
    """A named, validated workflow definition."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint("name", "version", name="uq_workflows_name_version"),
        CheckConstraint("version > 0", name="ck_workflows_positive_version"),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    workflow_definition: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    executions: Mapped[list["WorkflowExecution"]] = relationship(
        back_populates="workflow",
        passive_deletes="all",
    )
