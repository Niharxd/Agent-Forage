"""Operator identity persistence model."""

from uuid import UUID, uuid4

from sqlalchemy import String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from agentforge.database.base import Base
from agentforge.domain.models.mixins import TimestampMixin


class User(TimestampMixin, Base):
    """Minimal operator record; authentication is not yet specified."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        primary_key=True,
        default=uuid4,
        server_default=text("gen_random_uuid()"),
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True)
