from typing import Optional

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.competition import Competition


class Season(Base):
    """Saison eines Wettbewerbs."""

    __tablename__ = "seasons"
    __table_args__ = (UniqueConstraint("competition_id", "code"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), index=True)
    ws_season_id: Mapped[int] = mapped_column(unique=True)
    # soccerdata-Saisoncode (z. B. "2627")
    code: Mapped[str]

    competition: Mapped[Competition] = relationship()


class Stage(Base):
    """Phase einer Saison (z. B. Hauptrunde, Gruppenphase, K.-o.-Runde)."""

    __tablename__ = "stages"

    id: Mapped[int] = mapped_column(primary_key=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), index=True)
    ws_stage_id: Mapped[int] = mapped_column(unique=True)
    name: Mapped[Optional[str]]
    is_default: Mapped[bool] = mapped_column(default=False)

    season: Mapped[Season] = relationship()
