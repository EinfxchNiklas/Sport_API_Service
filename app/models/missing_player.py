from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MissingPlayer(Base):
    """Ausfallender Spieler eines Teams (laut Spielvorschau); ersetzt die alte Verletztentabelle."""

    __tablename__ = "missing_players"
    __table_args__ = (UniqueConstraint("team_id", "player_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"))
    # Das anstehende Spiel, dessen Vorschau den Ausfall gemeldet hat
    match_id: Mapped[Optional[int]] = mapped_column(ForeignKey("matches.id", ondelete="SET NULL"))
    reason: Mapped[Optional[str]]
    status: Mapped[Optional[str]]
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(ZoneInfo("Europe/Berlin")),
    )
