from datetime import datetime as _dt
from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.logging_config import get_logger
from app.models import NflGame, NflStanding, NflTeam
from app.schemas import NflGameRead, NflStandingWithTeam, NflTeamRead
from app.services.nfl_service import import_nfl_games_new, import_nfl_standings, import_nfl_teams

router = APIRouter(prefix="/nfl")
logger = get_logger(__name__)


@router.get("/teams", response_model=list[NflTeamRead])
def get_nfl_teams(conference: Optional[str] = None, db: Session = Depends(get_db)):
    q = db.query(NflTeam)
    if conference is not None:
        q = q.filter(NflTeam.conference == conference)
    teams = q.all()
    if not teams:
        try:
            import_nfl_teams(db)
        except Exception:
            logger.warning("Auto-import NFL Teams fehlgeschlagen", exc_info=True)
        q2 = db.query(NflTeam)
        if conference is not None:
            q2 = q2.filter(NflTeam.conference == conference)
        teams = q2.all()
    return teams


@router.get("/games")
def get_nfl_games(
    season: Optional[int] = None,
    week: Optional[int] = None,
    season_type: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Liefert NFL-Spiele (nfl_games) mit optionalem week/season_type-Filter.

    Ohne ``season``-Parameter wird das aktuelle Jahr verwendet.
    """
    season = season or _dt.now().year
    q = db.query(NflGame).filter(NflGame.season == season)
    if week is not None:
        q = q.filter(NflGame.week == week)
    if season_type is not None:
        q = q.filter(NflGame.season_type == season_type)
    games = q.order_by(NflGame.kickoff_time).all()

    if not games:
        try:
            _week = week or 1
            _type = season_type or "reg"
            import_nfl_games_new(db, game_week=_week, season=season, season_type=_type)
        except Exception:
            logger.warning(
                "Auto-import NFL Spiele fehlgeschlagen (season=%s week=%s)",
                season, week, exc_info=True,
            )
        q2 = db.query(NflGame).filter(NflGame.season == season)
        if week is not None:
            q2 = q2.filter(NflGame.week == week)
        if season_type is not None:
            q2 = q2.filter(NflGame.season_type == season_type)
        games = q2.order_by(NflGame.kickoff_time).all()

    return [NflGameRead.model_validate(g) for g in games]


@router.get("/standings", response_model=list[NflStandingWithTeam])
def get_nfl_standings(
    season: Optional[int] = None,
    conference: Optional[str] = None,
    division: Optional[str] = None,
    db: Session = Depends(get_db),
):
    _season = season or _dt.now().year
    q = db.query(NflStanding, NflTeam).join(NflTeam, NflStanding.team_id == NflTeam.id)
    q = q.filter(NflStanding.season == _season)
    if conference is not None:
        q = q.filter(NflTeam.conference == conference)
    if division is not None:
        q = q.filter(NflTeam.division == division)
    rows = q.order_by(NflStanding.division_rank.asc().nulls_last(), NflStanding.wins.desc()).all()

    if not rows:
        try:
            import_nfl_standings(db, season=_season)
        except Exception:
            logger.warning("Auto-import NFL Standings fehlgeschlagen (season=%s)", _season, exc_info=True)
        q2 = db.query(NflStanding, NflTeam).join(NflTeam, NflStanding.team_id == NflTeam.id)
        q2 = q2.filter(NflStanding.season == _season)
        if conference is not None:
            q2 = q2.filter(NflTeam.conference == conference)
        if division is not None:
            q2 = q2.filter(NflTeam.division == division)
        rows = q2.order_by(NflStanding.division_rank.asc().nulls_last(), NflStanding.wins.desc()).all()

    return [
        NflStandingWithTeam(
            id=standing.id,
            season=standing.season,
            team_name=team.name,
            team_abbreviation=team.abbreviation,
            conference=team.conference,
            division=team.division,
            wins=standing.wins,
            losses=standing.losses,
            ties=standing.ties,
            division_rank=standing.division_rank,
        )
        for standing, team in rows
    ]
