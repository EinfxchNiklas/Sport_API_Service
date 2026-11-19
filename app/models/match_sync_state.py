from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MatchSyncState(Base):
    """Synchronisationsstand eines Spiels (welche Daten wann zuletzt geladen wurden)."""

    __tablename__ = "match_sync_state"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    fixture_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    prematch_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    lineups_confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    details_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    details_final_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(default=0)
    last_error: Mapped[Optional[str]]
