from typing import Optional

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.region import Region


class Competition(Base):
    """Wettbewerb (z. B. Bundesliga) laut WhoScored."""

    __tablename__ = "competitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_tournament_id: Mapped[int] = mapped_column(unique=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"))
    # soccerdata-Schlüssel der Liga (z. B. "GER-Bundesliga")
    league_key: Mapped[str] = mapped_column(unique=True)
    name: Mapped[str]
    # URL-Slug (z. B. "bundesliga")
    slug: Mapped[str] = mapped_column(unique=True)
    # Format des Wettbewerbs: "league" | "cup" | "tournament"
    format: Mapped[Optional[str]]

    region: Mapped[Region] = relationship()
