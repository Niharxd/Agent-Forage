"""Workflow execution, attempt, approval, tool, and audit models."""

from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from agentforge.database.base import Base

if TYPE_CHECKING:
    from agentforge.domain.models.workflow import Workflow


class WorkflowExecution(Base):
    """A durable execution, including the state captured before planning."""

    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('submitted', 'planning', 'planned', 'queued', 'running', "
            "'waiting_approval', 'succeeded', 'failed', 'cancelled')",
            name="ck_workflow_executions_status",
        ),
        CheckConstraint(
            "plan_version IS NULL OR plan_version > 0",
            name="ck_execution_plan_version",
        ),
        CheckConstraint(
            "status NOT IN ('succeeded', 'failed', 'cancelled') OR completed_at IS NOT NULL",
            name="ck_terminal_execution_has_completion_time",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    workflow_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflows.id", ondelete="RESTRICT"),
        index=True,
    )
    original_task: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="submitted")
    plan_version: Mapped[int | None] = mapped_column(Integer)
    provider_mode: Mapped[str | None] = mapped_column(String(50))
    terminal_reason: Mapped[str | None] = mapped_column(Text)
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    workflow: Mapped["Workflow | None"] = relationship(back_populates="executions")
    steps: Mapped[list["ExecutionStep"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    tool_execution_records: Mapped[list["ToolExecutionRecord"]] = relationship(
        back_populates="execution",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    events: Mapped[list["ExecutionEvent"]] = relationship(
        back_populates="execution",
        passive_deletes="all",
        order_by="ExecutionEvent.occurred_at",
    )


class ExecutionStep(Base):
    """A persisted attempt for a stable task in a workflow execution."""

    __tablename__ = "execution_steps"
    __table_args__ = (
        UniqueConstraint(
            "execution_id",
            "task_id",
            "attempt_number",
            name="uq_execution_steps_task_attempt",
        ),
        CheckConstraint("attempt_number > 0", name="ck_execution_steps_positive_attempt"),
        CheckConstraint(
            "status IN ('pending', 'running', 'waiting_approval', 'succeeded', "
            "'failed', 'cancelled')",
            name="ck_execution_steps_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt_number: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending")
    input_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    output_data: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution: Mapped[WorkflowExecution] = relationship(back_populates="steps")
    approval_requests: Mapped[list["ApprovalRequest"]] = relationship(
        back_populates="execution_step",
        passive_deletes="all",
    )
    tool_execution_records: Mapped[list["ToolExecutionRecord"]] = relationship(
        back_populates="execution_step",
        passive_deletes="all",
    )


class ApprovalRequest(Base):
    """An approval gate bound to a specific safe action representation."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired')",
            name="ck_approval_requests_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND reviewed_at IS NULL) OR "
            "(status <> 'pending' AND reviewed_at IS NOT NULL)",
            name="ck_approval_review_timestamp",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("execution_steps.id", ondelete="SET NULL"),
        index=True,
    )
    action_description: Mapped[str] = mapped_column(Text, nullable=False)
    action_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    safe_arguments: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution: Mapped[WorkflowExecution] = relationship(back_populates="approval_requests")
    execution_step: Mapped[ExecutionStep | None] = relationship(back_populates="approval_requests")


class ToolExecutionRecord(Base):
    """A durable record of a registered tool invocation."""

    __tablename__ = "tool_execution_records"
    __table_args__ = (
        CheckConstraint(
            "status IN ('requested', 'awaiting_approval', 'running', 'succeeded', "
            "'failed', 'denied', 'ambiguous')",
            name="ck_tool_execution_records_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    execution_step_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("execution_steps.id", ondelete="SET NULL"),
        index=True,
    )
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="requested")
    input_summary: Mapped[str | None] = mapped_column(Text)
    output_summary: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    execution: Mapped[WorkflowExecution] = relationship(back_populates="tool_execution_records")
    execution_step: Mapped[ExecutionStep | None] = relationship(
        back_populates="tool_execution_records"
    )


class ExecutionEvent(Base):
    """Append-only lifecycle and audit event for an execution."""

    __tablename__ = "execution_events"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    execution_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    from_status: Mapped[str | None] = mapped_column(String(30))
    to_status: Mapped[str | None] = mapped_column(String(30))
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    reason: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        server_default=text("'{}'::jsonb"),
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    execution: Mapped[WorkflowExecution] = relationship(back_populates="events")
