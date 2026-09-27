import time
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from app.logging_config import get_logger
from app.models import (
    ConstructorStanding,
    Driver,
    DriverStanding,
    Race,
    RaceSession,
    SessionResult,
)
from app.services.datasources import OpenF1Client

logger = get_logger(__name__)
_BERLIN = ZoneInfo("Europe/Berlin")
# OpenF1 Free-Tier: max. 30 Requests/Minute -> 2s Abstand + Puffer
_OPENF1_REQUEST_INTERVAL_SECONDS = 2.1


def _parse_dt(value) -> datetime | None:
    if value is None:
        return None
    try:
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def import_f1_races(db: Session, year: int = 2025) -> dict:
    logger.info("import_f1_races start (year=%s)", year)
    created = updated = 0

    with OpenF1Client() as client:
        races_data = client.fetch_races(year)
        for rd in races_data:
            race = (
                db.query(Race)
                .filter_by(season=rd["season"], name=rd["name"])
                .first()
            )
            if race is None:
                race = Race(
                    season=rd["season"],
                    name=rd["name"],
                    date=_parse_dt(rd.get("date")),
                    status=rd.get("status"),
                    location=rd.get("location"),
                    country=rd.get("country"),
                    round=rd.get("round"),
                    external_id=rd.get("external_id"),
                )
                db.add(race)
                created += 1
            else:
                race.date = _parse_dt(rd.get("date"))
                race.status = rd.get("status")
                race.location = rd.get("location")
                race.country = rd.get("country")
                race.round = rd.get("round")
                race.external_id = rd.get("external_id")
                updated += 1

    db.commit()
    logger.info("import_f1_races done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_f1_drivers(db: Session, session_key: str = "latest") -> dict:
    logger.info("import_f1_drivers start (session_key=%s)", session_key)
    created = updated = 0

    with OpenF1Client() as client:
        drivers_data = client.fetch_drivers(session_key)
        for dd in drivers_data:
            number = dd.get("number")
            if number is not None:
                driver = db.query(Driver).filter_by(number=number).first()
            else:
                driver = db.query(Driver).filter_by(name=dd["name"]).first()

            if driver is None:
                driver = Driver(
                    name=dd["name"],
                    team=dd.get("team"),
                    number=number,
                    abbreviation=dd.get("abbreviation"),
                    country=dd.get("country"),
                    team_color=dd.get("team_color"),
                    external_id=dd.get("external_id"),
                )
                db.add(driver)
                created += 1
            else:
                driver.name = dd["name"]
                driver.team = dd.get("team")
                if number is not None:
                    driver.number = number
                driver.abbreviation = dd.get("abbreviation")
                driver.country = dd.get("country")
                driver.team_color = dd.get("team_color")
                driver.external_id = dd.get("external_id")
                updated += 1

    db.commit()
    logger.info("import_f1_drivers done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def _import_sessions_for_race(db: Session, race: Race, client: OpenF1Client) -> tuple[int, int]:
    """Hilfsfunktion: importiert Sessions für ein einzelnes Race-Objekt."""
    created = updated = 0
    sessions_data = client.fetch_sessions(race.external_id)
    for sd in sessions_data:
        ext_id = sd.get("external_id")
        session = (
            db.query(RaceSession).filter_by(external_id=ext_id).first()
            if ext_id
            else db.query(RaceSession).filter_by(race_id=race.id, name=sd["name"]).first()
        )
        if session is None:
            session = RaceSession(
                race_id=race.id,
                name=sd["name"],
                session_type=sd.get("session_type"),
                start_time=_parse_dt(sd.get("start_time")),
                end_time=_parse_dt(sd.get("end_time")),
                status=sd.get("status"),
                external_id=ext_id,
            )
            db.add(session)
            created += 1
        else:
            session.session_type = sd.get("session_type")
            session.start_time = _parse_dt(sd.get("start_time"))
            session.end_time = _parse_dt(sd.get("end_time"))
            session.status = sd.get("status")
            updated += 1
    return created, updated


def import_f1_sessions_for_race(db: Session, race: Race) -> dict:
    """Importiert Sessions gezielt für ein einzelnes Rennen (ein HTTP-Request)."""
    logger.info("import_f1_sessions_for_race start (race_id=%s, meeting_key=%s)", race.id, race.external_id)
    with OpenF1Client() as client:
        created, updated = _import_sessions_for_race(db, race, client)
    db.commit()
    logger.info("import_f1_sessions_for_race done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_f1_sessions(db: Session, year: int) -> dict:
    """Importiert Sessions für alle Rennwochenenden eines Jahres."""
    logger.info("import_f1_sessions start (year=%s)", year)
    created = updated = 0

    races = db.query(Race).filter(Race.season == str(year), Race.external_id.isnot(None)).all()
    with OpenF1Client() as client:
        for i, race in enumerate(races):
            if i > 0:
                # OpenF1 Free-Tier erlaubt nur 30 Requests/Minute -> min. 2s Abstand nötig
                time.sleep(_OPENF1_REQUEST_INTERVAL_SECONDS)
            c, u = _import_sessions_for_race(db, race, client)
            created += c
            updated += u

    db.commit()
    logger.info("import_f1_sessions done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_f1_session_results(db: Session, session_key: int) -> dict:
    """Importiert Ergebnisse einer einzelnen Session."""
    logger.info("import_f1_session_results start (session_key=%s)", session_key)

    race_session = db.query(RaceSession).filter_by(external_id=session_key).first()
    if race_session is None:
        logger.warning("import_f1_session_results: session not found for key=%s", session_key)
        return {"created": 0, "updated": 0}

    with OpenF1Client() as client:
        results_data = client.fetch_session_results(session_key)

    created = updated = 0
    for rd in results_data:
        driver_number = rd.get("driver_number")
        driver = db.query(Driver).filter_by(number=driver_number).first()
        if driver is None:
            logger.warning("import_f1_session_results: driver not found: %s", driver_number)
            continue

        result = db.query(SessionResult).filter_by(
            session_id=race_session.id, driver_id=driver.id
        ).first()
        if result is None:
            result = SessionResult(
                session_id=race_session.id,
                driver_id=driver.id,
                position=rd.get("position"),
                time=rd.get("time"),
                laps=rd.get("laps"),
                points=rd.get("points"),
                status=rd.get("status"),
            )
            db.add(result)
            created += 1
        else:
            result.position = rd.get("position")
            result.time = rd.get("time")
            result.laps = rd.get("laps")
            result.points = rd.get("points")
            result.status = rd.get("status")
            updated += 1

    db.commit()
    logger.info("import_f1_session_results done: created=%s updated=%s", created, updated)
    return {"created": created, "updated": updated}


def import_f1_standings(db: Session, year: int) -> dict:
    """Importiert Fahrer- und Konstrukteurs-Standings von OpenF1.

    Nutzt die Championship-Endpoints von OpenF1 (/championship_drivers,
    /championship_teams), die nach jeder Race-Session aktualisiert werden.
    Als Basis dient die jüngste abgeschlossene Race-Session des Jahres.
    """
    logger.info("import_f1_standings start (year=%s)", year)

    # Jüngste abgeschlossene Race-Session des Jahres finden
    latest_race = (
        db.query(RaceSession)
        .join(Race, RaceSession.race_id == Race.id)
        .filter(
            Race.season == str(year),
            RaceSession.session_type == "Race",
            RaceSession.status == "completed",
            RaceSession.external_id.isnot(None),
        )
        .order_by(RaceSession.start_time.desc())
        .first()
    )

    if latest_race is None:
        logger.warning(
            "import_f1_standings: Keine abgeschlossene Race-Session für year=%s gefunden", year
        )
        return {"driver_standings": 0, "constructor_standings": 0}

    logger.info(
        "import_f1_standings: Nutze session_key=%s als Basis", latest_race.external_id
    )

    with OpenF1Client() as client:
        driver_data = client.fetch_championship_drivers(latest_race.external_id)
        team_data = client.fetch_championship_teams(latest_race.external_id)

    season_str = str(year)
    db.query(DriverStanding).filter_by(season=season_str).delete()
    db.query(ConstructorStanding).filter_by(season=season_str).delete()
    db.flush()

    driver_count = 0
    for dd in driver_data:
        driver = db.query(Driver).filter_by(number=dd["driver_number"]).first()
        if driver is None:
            logger.warning(
                "import_f1_standings: Fahrer %s nicht in DB", dd["driver_number"]
            )
            continue
        db.add(DriverStanding(
            season=season_str,
            driver_id=driver.id,
            position=dd.get("position"),
            points=dd.get("points", 0),
            wins=0,  # OpenF1 Championship-Endpoint liefert keine Siege
        ))
        driver_count += 1

    team_count = 0
    for td in team_data:
        team_name = td.get("team_name")
        # Teamfarbe aus einem passenden Fahrer-Eintrag ableiten
        driver_with_color = db.query(Driver).filter_by(team=team_name).first()
        team_color = driver_with_color.team_color if driver_with_color else None
        db.add(ConstructorStanding(
            season=season_str,
            team=team_name,
            team_color=team_color,
            position=td.get("position"),
            points=td.get("points", 0),
            wins=0,
        ))
        team_count += 1

    db.commit()
    logger.info(
        "import_f1_standings done: drivers=%s constructors=%s", driver_count, team_count
    )
    return {"driver_standings": driver_count, "constructor_standings": team_count}
