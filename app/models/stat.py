from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StatType(Base):
    """Katalog der Statistik-Schlüssel (z. B. "shotsTotal", "passesAccurate")."""

    __tablename__ = "stat_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(unique=True)


class TeamMatchStat(Base):
    __tablename__ = "team_match_stats"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    stat_type_id: Mapped[int] = mapped_column(ForeignKey("stat_types.id"), primary_key=True)
    value: Mapped[float]


class PlayerMatchStat(Base):
    __tablename__ = "player_match_stats"

    appearance_id: Mapped[int] = mapped_column(
        ForeignKey("appearances.id", ondelete="CASCADE"), primary_key=True
    )
    stat_type_id: Mapped[int] = mapped_column(ForeignKey("stat_types.id"), primary_key=True)
    value: Mapped[float]
