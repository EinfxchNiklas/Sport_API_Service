from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Manager(Base):
    """Trainer eines Teams in einem Spiel."""

    __tablename__ = "managers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
