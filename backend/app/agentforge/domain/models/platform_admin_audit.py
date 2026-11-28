"""Append-only record of platform operator account actions.

PostgreSQL migration triggers reject UPDATE and DELETE operations. The API
does not expose audit mutation routes.
"""

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, Uuid, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from agentforge.database.base import Base


class PlatformAdminAudit(Base):
    __tablename__ = "platform_admin_audit"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'operator'")
    )
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    target_user_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
