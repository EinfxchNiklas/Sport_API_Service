from typing import Optional

from sqlalchemy import BigInteger, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchIncident(Base):
    """Spielereignis (Tor, Eigentor, Elfmetertor, Karte)."""

    __tablename__ = "match_incidents"
    __table_args__ = (UniqueConstraint("match_id", "ws_event_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    ws_event_id: Mapped[int] = mapped_column(BigInteger)
    # "goal" | "own_goal" | "penalty_goal" | "card"
    type: Mapped[str]
    # "yellow" | "second_yellow" | "red"
    card_type: Mapped[Optional[str]]
    minute: Mapped[int]
    expanded_minute: Mapped[Optional[int]]
    period: Mapped[Optional[str]]
    player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))
    related_player_id: Mapped[Optional[int]] = mapped_column(ForeignKey("players.id"))
