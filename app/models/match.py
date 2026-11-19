from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import CheckConstraint, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.models.manager import Manager
from app.models.referee import Referee
from app.models.season import Stage
from app.models.team import Team
from app.models.venue import Venue


def _berlin_now() -> datetime:
    return datetime.now(ZoneInfo("Europe/Berlin"))


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (CheckConstraint("home_team_id <> away_team_id", name="ck_matches_teams_differ"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    ws_match_id: Mapped[int] = mapped_column(unique=True)
    stage_id: Mapped[int] = mapped_column(ForeignKey("stages.id"), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    kickoff_time: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), index=True)
    # "scheduled" | "live" | "finished" | "postponed" | "cancelled" | "abandoned"
    status: Mapped[str] = mapped_column(default="scheduled", index=True)
    home_score: Mapped[Optional[int]]
    away_score: Mapped[Optional[int]]
    ht_home_score: Mapped[Optional[int]]
    ht_away_score: Mapped[Optional[int]]
    et_home_score: Mapped[Optional[int]]
    et_away_score: Mapped[Optional[int]]
    pen_home_score: Mapped[Optional[int]]
    pen_away_score: Mapped[Optional[int]]
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    first_half_ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    second_half_started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    venue_id: Mapped[Optional[int]] = mapped_column(ForeignKey("venues.id"))
    referee_id: Mapped[Optional[int]] = mapped_column(ForeignKey("referees.id"))
    attendance: Mapped[Optional[int]]
    last_updated: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_berlin_now,
        onupdate=_berlin_now,
    )

    stage: Mapped[Stage] = relationship()
    home_team: Mapped[Team] = relationship(foreign_keys=[home_team_id])
    away_team: Mapped[Team] = relationship(foreign_keys=[away_team_id])
    venue: Mapped[Optional[Venue]] = relationship()
    referee: Mapped[Optional[Referee]] = relationship()


class MatchTeam(Base):
    """Team-spezifische Angaben zu einem Spiel (Trainer, Durchschnittsalter)."""

    __tablename__ = "match_teams"

    match_id: Mapped[int] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"), primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    manager_id: Mapped[Optional[int]] = mapped_column(ForeignKey("managers.id"))
    average_age: Mapped[Optional[float]]

    manager: Mapped[Optional[Manager]] = relationship()
