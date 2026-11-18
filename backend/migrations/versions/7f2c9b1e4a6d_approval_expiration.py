"""Add durable approval expiration timestamps."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7f2c9b1e4a6d"
down_revision: Union[str, Sequence[str], None] = "5c8a1d907e42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "approval_requests",
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now() + interval '24 hours'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("approval_requests", "expires_at")
