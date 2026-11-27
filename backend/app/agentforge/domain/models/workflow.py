"""Versioned workflow persistence model."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
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
    from agentforge.domain.models.user import User
    from agentforge.domain.models.workspace import Workspace


class Workflow(TimestampMixin, Base):
    """A named, validated workflow definition."""

    __tablename__ = "workflows"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "name",
            "version",
            name="uq_workflows_workspace_name_version",
        ),
        UniqueConstraint("workspace_id", "id", name="uq_workflows_workspace_id"),
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
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    updated_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    workspace: Mapped["Workspace"] = relationship(back_populates="workflows")
    created_by: Mapped["User | None"] = relationship(
        foreign_keys=[created_by_user_id],
    )
    updated_by: Mapped["User | None"] = relationship(
        foreign_keys=[updated_by_user_id],
    )
    executions: Mapped[list["WorkflowExecution"]] = relationship(
        back_populates="workflow",
        foreign_keys="WorkflowExecution.workflow_id",
        passive_deletes="all",
        overlaps="workspace",
    )
