from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import NflGame, NflStanding, NflTeam
from app.services.datasources import Tank01Client

logger = get_logger(__name__)
_BERLIN = ZoneInfo("Europe/Berlin")


def import_nfl_teams(db: Session) -> dict:
    logger.info("import_nfl_teams start")
    created = updated = 0

    with Tank01Client() as client:
        teams_data = client.fetch_nfl_teams()
        for td in teams_data:
            team = db.query(NflTeam).filter_by(name=td["name"]).first()
            if team is None:
                team = NflTeam(**td)
                db.add(team)
                created += 1
            else:
                team.conference = td.get("conference")
                team.division = td.get("division")
                team.abbreviation = td.get("abbreviation")
                team.city = td.get("city")
                team.logo_url = td.get("logo_url")
                team.external_id = td.get("external_id")
                updated += 1

    db.commit()
    logger.info("import_nfl_teams done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_nfl_standings(db: Session, season: int) -> dict:
    """Importiert NFL-Standings (W/L/D) für eine Saison aus Tank01."""
    logger.info("import_nfl_standings start (season=%s)", season)

    with Tank01Client() as client:
        standings_data = client.fetch_standings(season)

    created = updated = 0
    for sd in standings_data:
        team = db.query(NflTeam).filter_by(abbreviation=sd["team_abbreviation"]).first()
        if team is None:
            logger.warning("import_nfl_standings: team not found: %s", sd["team_abbreviation"])
            continue

        standing = db.query(NflStanding).filter_by(season=season, team_id=team.id).first()
        if standing is None:
            standing = NflStanding(
                season=season,
                team_id=team.id,
                wins=sd.get("wins", 0),
                losses=sd.get("losses", 0),
                ties=sd.get("ties", 0),
                division_rank=sd.get("division_rank"),
            )
            db.add(standing)
            created += 1
        else:
            standing.wins = sd.get("wins", 0)
            standing.losses = sd.get("losses", 0)
            standing.ties = sd.get("ties", 0)
            standing.division_rank = sd.get("division_rank")
            updated += 1

    db.commit()
    logger.info("import_nfl_standings done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_nfl_games_new(
    db: Session,
    game_week: int = 1,
    season: int = 2025,
    season_type: str = "reg",
) -> dict:
    """Importiert NFL-Spiele in die nfl_games-Tabelle (NflTeam per Abkürzung)."""
    logger.info(
        "import_nfl_games_new start (week=%s, season=%s, type=%s)",
        game_week,
        season,
        season_type,
    )
    now = _BERLIN
    created = updated = 0

    with Tank01Client() as client:
        games_data = client.fetch_games(game_week, season, season_type)

    for gd in games_data:
        home_abv = gd.get("home_team")
        away_abv = gd.get("away_team")
        home_team = db.query(NflTeam).filter_by(abbreviation=home_abv).first()
        away_team = db.query(NflTeam).filter_by(abbreviation=away_abv).first()

        if home_team is None or away_team is None:
            logger.warning(
                "import_nfl_games_new: team not found home=%s away=%s", home_abv, away_abv
            )
            continue

        ext_id = gd.get("external_id")
        game = (
            db.query(NflGame).filter_by(external_id=ext_id).first()
            if ext_id
            else None
        )

        kickoff_raw = gd.get("kickoff_time")
        kickoff: datetime | None = None
        if kickoff_raw:
            try:
                kickoff = datetime.fromisoformat(str(kickoff_raw))
            except (ValueError, TypeError):
                kickoff = None

        if game is None:
            game = NflGame(
                season=gd.get("season", season),
                season_type=gd.get("season_type", season_type),
                week=gd.get("week", game_week),
                home_team_id=home_team.id,
                away_team_id=away_team.id,
                kickoff_time=kickoff,
                status=gd.get("status"),
                home_score=gd.get("home_score"),
                away_score=gd.get("away_score"),
                external_id=ext_id,
                last_updated=datetime.now(ZoneInfo("Europe/Berlin")),
            )
            db.add(game)
            created += 1
        else:
            game.status = gd.get("status")
            game.home_score = gd.get("home_score")
            game.away_score = gd.get("away_score")
            game.kickoff_time = kickoff
            game.last_updated = datetime.now(ZoneInfo("Europe/Berlin"))
            updated += 1

    db.commit()
    logger.info("import_nfl_games_new done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}
