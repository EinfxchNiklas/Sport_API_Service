from typing import Optional

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class Formation(Base):
    """Formation eines Teams in einem Spielabschnitt (Wechsel erzeugen neue Formation)."""

    __tablename__ = "formations"
    __table_args__ = (UniqueConstraint("match_id", "team_id", "start_minute"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    start_minute: Mapped[int]
    end_minute: Mapped[Optional[int]]
    period: Mapped[Optional[int]]
    name: Mapped[str]
    captain_player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))


class FormationPosition(Base):
    """Position (Slot) eines Spielers innerhalb einer Formation."""

    __tablename__ = "formation_positions"

    formation_id: Mapped[int] = mapped_column(
        ForeignKey("formations.id", ondelete="CASCADE"), primary_key=True
    )
    slot: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))
    vertical: Mapped[Optional[float]]
    horizontal: Mapped[Optional[float]]
