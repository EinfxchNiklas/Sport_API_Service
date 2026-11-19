from typing import Optional

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.player import Player


class Appearance(Base):
    """Einsatz eines Spielers in einem Spiel (Kader/Aufstellung inkl. Bewertung)."""

    __tablename__ = "appearances"
    __table_args__ = (UniqueConstraint("match_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), index=True)
    shirt_no: Mapped[Optional[int]]
    position: Mapped[Optional[str]]
    is_first_eleven: Mapped[bool] = mapped_column(default=False)
    is_man_of_the_match: Mapped[bool] = mapped_column(default=False)
    age: Mapped[Optional[int]]
    rating: Mapped[Optional[float]]
    subbed_in_minute: Mapped[Optional[int]]
    subbed_out_minute: Mapped[Optional[int]]

    player: Mapped[Player] = relationship()
