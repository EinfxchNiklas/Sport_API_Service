from typing import Optional

from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Country(Base):
    """Land eines Teams (Nationalität/Verbandszugehörigkeit)."""

    __tablename__ = "countries"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True)
    code: Mapped[Optional[str]] = mapped_column(unique=True)
