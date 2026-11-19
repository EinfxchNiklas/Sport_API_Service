from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import (
    Base,
    Competition,
    Driver,
    Match,
    NflTeam,
    Race,
    Region,
    Season,
    Stage,
    Team,
)

_BERLIN = ZoneInfo("Europe/Berlin")
logger = get_logger(__name__)


def seed(db: Session) -> None:
    # Region
    region = db.query(Region).filter_by(ws_region_id=81).first()
    if region is None:
        region = Region(ws_region_id=81, name="Germany")
        db.add(region)
        db.flush()
        logger.info("Inserted Region: Germany")
    else:
        logger.info("Skipped Region: Germany (already exists)")

    # Competition
    competition = db.query(Competition).filter_by(ws_tournament_id=3).first()
    if competition is None:
        competition = Competition(
            ws_tournament_id=3,
            region_id=region.id,
            league_key="GER-Bundesliga",
            name="Bundesliga",
            slug="bundesliga",
            format="league",
        )
        db.add(competition)
        db.flush()
        logger.info("Inserted Competition: Bundesliga")
    else:
        logger.info("Skipped Competition: Bundesliga (already exists)")

    # Season (ws_season_id ist ein Platzhalter)
    season = db.query(Season).filter_by(competition_id=competition.id, code="2627").first()
    if season is None:
        season = Season(competition_id=competition.id, ws_season_id=999001, code="2627")
        db.add(season)
        db.flush()
        logger.info("Inserted Season: Bundesliga 2627")
    else:
        logger.info("Skipped Season: Bundesliga 2627 (already exists)")

    # Stage (ws_stage_id ist ein Platzhalter)
    stage = db.query(Stage).filter_by(season_id=season.id, is_default=True).first()
    if stage is None:
        stage = Stage(season_id=season.id, ws_stage_id=999001, name="Bundesliga", is_default=True)
        db.add(stage)
        db.flush()
        logger.info("Inserted Stage: Bundesliga 2627 (default)")
    else:
        logger.info("Skipped Stage: Bundesliga 2627 (already exists)")

    # Teams (ws_team_id sind Platzhalter)
    fcb = db.query(Team).filter_by(name="FC Bayern München").first()
    if fcb is None:
        fcb = Team(ws_team_id=999001, name="FC Bayern München")
        db.add(fcb)
        db.flush()
        logger.info("Inserted Team: FC Bayern München")
    else:
        logger.info("Skipped Team: FC Bayern München (already exists)")

    bvb = db.query(Team).filter_by(name="Borussia Dortmund").first()
    if bvb is None:
        bvb = Team(ws_team_id=999002, name="Borussia Dortmund")
        db.add(bvb)
        db.flush()
        logger.info("Inserted Team: Borussia Dortmund")
    else:
        logger.info("Skipped Team: Borussia Dortmund (already exists)")

    # Match (ws_match_id ist ein Platzhalter)
    match = (
        db.query(Match)
        .filter_by(
            stage_id=stage.id,
            home_team_id=fcb.id,
            away_team_id=bvb.id,
        )
        .first()
    )
    if match is None:
        match = Match(
            ws_match_id=999001,
            stage_id=stage.id,
            home_team_id=fcb.id,
            away_team_id=bvb.id,
            kickoff_time=datetime(2026, 9, 19, 15, 30, tzinfo=_BERLIN),
            status="scheduled",
            last_updated=datetime.now(_BERLIN),
        )
        db.add(match)
        logger.info("Inserted Match: FC Bayern München vs Borussia Dortmund")
    else:
        logger.info("Skipped Match: FC Bayern München vs Borussia Dortmund (already exists)")

    # Race
    race = db.query(Race).filter_by(name="Test Grand Prix", season="2025").first()
    if race is None:
        race = Race(
            name="Test Grand Prix",
            season="2025",
            date=datetime(2025, 10, 5, 14, 0, tzinfo=_BERLIN),
            status="scheduled",
        )
        db.add(race)
        logger.info("Inserted Race: Test Grand Prix")
    else:
        logger.info("Skipped Race: Test Grand Prix (already exists)")

    # Driver
    driver = db.query(Driver).filter_by(name="Max Mustermann").first()
    if driver is None:
        driver = Driver(name="Max Mustermann", team="Test Racing", number=1)
        db.add(driver)
        logger.info("Inserted Driver: Max Mustermann")
    else:
        logger.info("Skipped Driver: Max Mustermann (already exists)")

    # NflTeam
    nfl_team = db.query(NflTeam).filter_by(name="Kansas City Chiefs").first()
    if nfl_team is None:
        nfl_team = NflTeam(name="Kansas City Chiefs", conference="AFC", division="West")
        db.add(nfl_team)
        logger.info("Inserted NflTeam: Kansas City Chiefs")
    else:
        logger.info("Skipped NflTeam: Kansas City Chiefs (already exists)")

    db.commit()


if __name__ == "__main__":
    from app.database.session import SessionLocal, engine

    Base.metadata.create_all(engine)
    db = SessionLocal()
    try:
        seed(db)
        print("Seed erfolgreich abgeschlossen.")
    finally:
        db.close()
