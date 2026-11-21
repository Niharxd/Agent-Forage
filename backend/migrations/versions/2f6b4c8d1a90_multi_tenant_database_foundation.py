"""Add the database foundation for users and workspace tenancy.

Revision ID: 2f6b4c8d1a90
Revises: 7f2c9b1e4a6d
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "2f6b4c8d1a90"
down_revision: Union[str, Sequence[str], None] = "7f2c9b1e4a6d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT lower(btrim(email)) AS normalized_email
                FROM users
                GROUP BY lower(btrim(email))
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot normalize users.email because normalized values would duplicate';
            END IF;
        END $$;
        """
    )
    op.execute("UPDATE users SET email = lower(btrim(email))")
    op.drop_constraint("users_email_key", "users", type_="unique")
    op.create_check_constraint("ck_users_normalized_email", "users", "email = lower(btrim(email))")

    op.add_column("users", sa.Column("password_hash", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "account_status",
            sa.String(length=20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE users SET account_status = 'active'")
    op.create_check_constraint(
        "ck_users_account_status",
        "users",
        "account_status IN ('pending', 'active', 'suspended', 'deleted')",
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)

    op.create_table(
        "workspaces",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'deleted')",
            name="ck_workspaces_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False)
    op.create_index(op.f("ix_workspaces_slug"), "workspaces", ["slug"], unique=True)

    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column(
            "joined_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member')",
            name="ck_workspace_memberships_role",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
    )
    op.create_index(
        op.f("ix_workspace_memberships_workspace_id"),
        "workspace_memberships",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workspace_memberships_user_id"),
        "workspace_memberships",
        ["user_id"],
        unique=False,
    )

    op.execute(
        """
        INSERT INTO users (
            id, email, password_hash, account_status,
            created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            'legacy-operator@local.invalid',
            NULL,
            'active',
            now(),
            now()
        WHERE NOT EXISTS (SELECT 1 FROM users)
        """
    )
    op.execute(
        """
        INSERT INTO workspaces (
            id, name, slug, owner_id, status, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            'Legacy Operator Workspace',
            'legacy-operator',
            (
                SELECT id
                FROM users
                ORDER BY created_at ASC, id ASC
                LIMIT 1
            ),
            'active',
            now(),
            now()
        """
    )
    op.execute(
        """
        INSERT INTO workspace_memberships (
            id, workspace_id, user_id, role, joined_at, created_at, updated_at
        )
        SELECT
            gen_random_uuid(),
            workspaces.id,
            workspaces.owner_id,
            'owner',
            now(),
            now(),
            now()
        FROM workspaces
        WHERE workspaces.slug = 'legacy-operator'
        """
    )

    op.add_column("workflows", sa.Column("workspace_id", sa.Uuid(), nullable=True))
    op.add_column("workflows", sa.Column("created_by_user_id", sa.Uuid(), nullable=True))
    op.add_column("workflows", sa.Column("updated_by_user_id", sa.Uuid(), nullable=True))
    op.create_index(op.f("ix_workflows_workspace_id"), "workflows", ["workspace_id"], unique=False)
    op.create_index(
        op.f("ix_workflows_created_by_user_id"),
        "workflows",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflows_updated_by_user_id"),
        "workflows",
        ["updated_by_user_id"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_workflows_workspace_id",
        "workflows",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workflows_created_by_user_id",
        "workflows",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflows_updated_by_user_id",
        "workflows",
        "users",
        ["updated_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.execute(
        """
        UPDATE workflows
        SET
            workspace_id = (SELECT id FROM workspaces WHERE slug = 'legacy-operator'),
            created_by_user_id = (SELECT owner_id FROM workspaces WHERE slug = 'legacy-operator'),
            updated_by_user_id = (SELECT owner_id FROM workspaces WHERE slug = 'legacy-operator')
        """
    )
    op.alter_column("workflows", "workspace_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_constraint("uq_workflows_name_version", "workflows", type_="unique")
    op.create_unique_constraint(
        "uq_workflows_workspace_name_version",
        "workflows",
        ["workspace_id", "name", "version"],
    )
    op.create_unique_constraint(
        "uq_workflows_workspace_id",
        "workflows",
        ["workspace_id", "id"],
    )

    op.add_column(
        "workflow_executions",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "workflow_executions",
        sa.Column("created_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "workflow_executions",
        sa.Column("started_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "workflow_executions",
        sa.Column("cancelled_by_user_id", sa.Uuid(), nullable=True),
    )
    op.create_index(
        op.f("ix_workflow_executions_workspace_id"),
        "workflow_executions",
        ["workspace_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_created_by_user_id"),
        "workflow_executions",
        ["created_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_started_by_user_id"),
        "workflow_executions",
        ["started_by_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_workflow_executions_cancelled_by_user_id"),
        "workflow_executions",
        ["cancelled_by_user_id"],
        unique=False,
    )
    op.execute(
        """
        UPDATE workflow_executions
        SET
            workspace_id = COALESCE(
                (SELECT workflows.workspace_id
                 FROM workflows
                 WHERE workflows.id = workflow_executions.workflow_id),
                (SELECT id FROM workspaces WHERE slug = 'legacy-operator')
            ),
            created_by_user_id = (
                SELECT owner_id FROM workspaces WHERE slug = 'legacy-operator'
            )
        """
    )
    op.alter_column(
        "workflow_executions",
        "workspace_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.create_foreign_key(
        "fk_workflow_executions_workspace_id",
        "workflow_executions",
        "workspaces",
        ["workspace_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_workflow_executions_created_by_user_id",
        "workflow_executions",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflow_executions_started_by_user_id",
        "workflow_executions",
        "users",
        ["started_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflow_executions_cancelled_by_user_id",
        "workflow_executions",
        "users",
        ["cancelled_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_workflow_executions_workspace_workflow",
        "workflow_executions",
        "workflows",
        ["workspace_id", "workflow_id"],
        ["workspace_id", "id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_workflow_executions_workspace_workflow",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflow_executions_cancelled_by_user_id",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflow_executions_started_by_user_id",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflow_executions_created_by_user_id",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflow_executions_workspace_id",
        "workflow_executions",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_workflow_executions_cancelled_by_user_id"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_started_by_user_id"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_created_by_user_id"),
        table_name="workflow_executions",
    )
    op.drop_index(
        op.f("ix_workflow_executions_workspace_id"),
        table_name="workflow_executions",
    )
    op.drop_column("workflow_executions", "cancelled_by_user_id")
    op.drop_column("workflow_executions", "started_by_user_id")
    op.drop_column("workflow_executions", "created_by_user_id")
    op.drop_column("workflow_executions", "workspace_id")

    op.drop_constraint(
        "uq_workflows_workspace_id",
        "workflows",
        type_="unique",
    )
    op.drop_constraint(
        "uq_workflows_workspace_name_version",
        "workflows",
        type_="unique",
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT name, version
                FROM workflows
                GROUP BY name, version
                HAVING count(*) > 1
            ) THEN
                RAISE EXCEPTION
                    'Cannot restore global workflow uniqueness across workspaces';
            END IF;
        END $$;
        """
    )
    op.create_unique_constraint(
        "uq_workflows_name_version",
        "workflows",
        ["name", "version"],
    )
    op.drop_constraint(
        "fk_workflows_updated_by_user_id",
        "workflows",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflows_created_by_user_id",
        "workflows",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_workflows_workspace_id",
        "workflows",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_workflows_updated_by_user_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_created_by_user_id"), table_name="workflows")
    op.drop_index(op.f("ix_workflows_workspace_id"), table_name="workflows")
    op.drop_column("workflows", "updated_by_user_id")
    op.drop_column("workflows", "created_by_user_id")
    op.drop_column("workflows", "workspace_id")

    op.drop_index(
        op.f("ix_workspace_memberships_user_id"),
        table_name="workspace_memberships",
    )
    op.drop_index(
        op.f("ix_workspace_memberships_workspace_id"),
        table_name="workspace_memberships",
    )
    op.drop_table("workspace_memberships")
    op.drop_index(op.f("ix_workspaces_slug"), table_name="workspaces")
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces")
    op.drop_table("workspaces")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_constraint("ck_users_account_status", "users", type_="check")
    op.drop_constraint("ck_users_normalized_email", "users", type_="check")
    op.create_unique_constraint("users_email_key", "users", ["email"])
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "account_status")
    op.drop_column("users", "password_hash")
