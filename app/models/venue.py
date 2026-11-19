from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Venue(Base):
    """Spielstätte."""

    __tablename__ = "venues"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
