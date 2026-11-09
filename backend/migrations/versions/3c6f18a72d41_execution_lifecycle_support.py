"""Support workflow-engine lifecycle states and ordered execution events.

Revision ID: 3c6f18a72d41
Revises: 10aad1807874
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c6f18a72d41"
down_revision: Union[str, Sequence[str], None] = "10aad1807874"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_LEGACY_EXECUTION_STATUSES = (
    "'submitted', 'planning', 'planned', 'queued', 'running', "
    "'waiting_approval', 'succeeded', 'failed', 'cancelled'"
)
_EXECUTION_STATUSES = f"{_LEGACY_EXECUTION_STATUSES}, 'pending', 'completed'"
_LEGACY_STEP_STATUSES = (
    "'pending', 'running', 'waiting_approval', 'succeeded', 'failed', 'cancelled'"
)
_STEP_STATUSES = f"{_LEGACY_STEP_STATUSES}, 'completed', 'blocked', 'skipped'"


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_constraint(
        "ck_workflow_executions_status",
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workflow_executions_status",
        "workflow_executions",
        f"status IN ({_EXECUTION_STATUSES})",
    )
    op.drop_constraint(
        "ck_terminal_execution_has_completion_time",
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_terminal_execution_has_completion_time",
        "workflow_executions",
        "status NOT IN ('succeeded', 'failed', 'cancelled', 'completed') "
        "OR completed_at IS NOT NULL",
    )
    op.drop_constraint("ck_execution_steps_status", "execution_steps", type_="check")
    op.create_check_constraint(
        "ck_execution_steps_status",
        "execution_steps",
        f"status IN ({_STEP_STATUSES})",
    )

    op.execute("DROP TRIGGER execution_events_are_immutable ON execution_events")
    op.add_column(
        "execution_events",
        sa.Column("sequence_number", sa.Integer(), nullable=True),
    )
    op.execute(
        """
        WITH ordered_events AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY execution_id
                       ORDER BY occurred_at, id
                   ) AS sequence_number
            FROM execution_events
        )
        UPDATE execution_events AS events
        SET sequence_number = ordered_events.sequence_number
        FROM ordered_events
        WHERE events.id = ordered_events.id
        """
    )
    op.alter_column("execution_events", "sequence_number", nullable=False)
    op.create_unique_constraint(
        "uq_execution_events_sequence",
        "execution_events",
        ["execution_id", "sequence_number"],
    )
    op.execute(
        """
        CREATE TRIGGER execution_events_are_immutable
        BEFORE UPDATE OR DELETE ON execution_events
        FOR EACH ROW EXECUTE FUNCTION prevent_execution_event_mutation()
        """
    )


def downgrade() -> None:
    """Downgrade schema, mapping new statuses to the closest legacy states."""
    op.execute("DROP TRIGGER execution_events_are_immutable ON execution_events")
    op.drop_constraint("uq_execution_events_sequence", "execution_events", type_="unique")
    op.drop_column("execution_events", "sequence_number")
    op.execute(
        """
        CREATE TRIGGER execution_events_are_immutable
        BEFORE UPDATE OR DELETE ON execution_events
        FOR EACH ROW EXECUTE FUNCTION prevent_execution_event_mutation()
        """
    )

    op.execute(
        """
        UPDATE workflow_executions
        SET status = CASE status
            WHEN 'pending' THEN 'planned'
            WHEN 'completed' THEN 'succeeded'
            ELSE status
        END
        WHERE status IN ('pending', 'completed')
        """
    )
    op.execute(
        """
        UPDATE execution_steps
        SET status = CASE status
            WHEN 'completed' THEN 'succeeded'
            WHEN 'blocked' THEN 'failed'
            WHEN 'skipped' THEN 'cancelled'
            ELSE status
        END
        WHERE status IN ('completed', 'blocked', 'skipped')
        """
    )
    op.drop_constraint(
        "ck_workflow_executions_status",
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_workflow_executions_status",
        "workflow_executions",
        f"status IN ({_LEGACY_EXECUTION_STATUSES})",
    )
    op.drop_constraint(
        "ck_terminal_execution_has_completion_time",
        "workflow_executions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_terminal_execution_has_completion_time",
        "workflow_executions",
        "status NOT IN ('succeeded', 'failed', 'cancelled') OR completed_at IS NOT NULL",
    )
    op.drop_constraint("ck_execution_steps_status", "execution_steps", type_="check")
    op.create_check_constraint(
        "ck_execution_steps_status",
        "execution_steps",
        f"status IN ({_LEGACY_STEP_STATUSES})",
    )
