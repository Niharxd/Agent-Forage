"""Persist the safe tool identifier on approval requests."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "5c8a1d907e42"
down_revision: Union[str, Sequence[str], None] = "3c6f18a72d41"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("approval_requests", sa.Column("tool_id", sa.String(length=100), nullable=True))


def downgrade() -> None:
    op.drop_column("approval_requests", "tool_id")
