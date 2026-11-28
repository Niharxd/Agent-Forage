"""Add audit records for platform operator account actions."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "4a81b91d6c20"
down_revision: Union[str, Sequence[str], None] = "a6c21f4d8e30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_admin_audit",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("actor_type", sa.String(20), server_default=sa.text("'operator'"), nullable=False),
        sa.Column("action", sa.String(40), nullable=False),
        sa.Column("target_user_id", sa.Uuid(), nullable=False),
        sa.Column("details", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_platform_admin_audit_occurred_at", "platform_admin_audit", ["occurred_at"])
    op.execute(
        """
        CREATE FUNCTION prevent_platform_admin_audit_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'platform admin audit records are immutable';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute(
        """
        CREATE TRIGGER platform_admin_audit_is_immutable
        BEFORE UPDATE OR DELETE ON platform_admin_audit
        FOR EACH ROW EXECUTE FUNCTION prevent_platform_admin_audit_mutation()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER platform_admin_audit_is_immutable ON platform_admin_audit")
    op.execute("DROP FUNCTION prevent_platform_admin_audit_mutation()")
    op.drop_index("ix_platform_admin_audit_occurred_at", table_name="platform_admin_audit")
    op.drop_table("platform_admin_audit")
