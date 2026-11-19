from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Region(Base):
    """Region/Land eines Wettbewerbs laut WhoScored (z. B. Germany, Europe)."""

    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_region_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[str]
