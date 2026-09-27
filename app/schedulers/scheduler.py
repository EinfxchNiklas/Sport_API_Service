from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone

from apscheduler.events import EVENT_JOB_ERROR, EVENT_JOB_EXECUTED, EVENT_JOB_MISSED, JobExecutionEvent
from apscheduler.jobstores.base import JobLookupError
from apscheduler.schedulers.background import BackgroundScheduler

from app.config import settings
from app.logging_config import get_logger

logger = get_logger(__name__)

_scheduler: BackgroundScheduler | None = None

# Ringpuffer der letzten Job-Ausführungen (neueste zuerst), nur In-Memory.
_JOB_HISTORY_MAXLEN = 100
_job_history: deque[dict] = deque(maxlen=_JOB_HISTORY_MAXLEN)

# Puffer nach session.end_time bevor Ergebnisse bei OpenF1 verfügbar sind.
_RESULTS_BUFFER = timedelta(minutes=15)

# Fallback-Puffer für Sessions ohne gespeichertes end_time (alter Datenstand).
# Basiert auf start_time + längste mögliche Session (Race ~2h) + API-Puffer (1h).
_SESSION_DURATION_BUFFER = timedelta(hours=4)


def _tz(dt: datetime) -> datetime:
    """Stellt sicher dass ein datetime timezone-aware ist (UTC als Default)."""
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(timezone=settings.timezone)
    return _scheduler


def start_scheduler() -> None:
    scheduler = get_scheduler()
    if not scheduler.running:
        scheduler.start()
        # Nächtlicher Session-Status-Update: täglich um 03:00 Uhr Berliner Zeit
        scheduler.add_job(
            update_session_statuses,
            trigger="cron",
            hour=3,
            minute=0,
            id="nightly_session_status_update",
            replace_existing=True,
        )
        # Stündlicher F1-Daten-Job: fehlende Sessionergebnisse nachladen
        scheduler.add_job(
            fetch_missing_f1_data,
            trigger="interval",
            hours=1,
            id="hourly_f1_data_fetch",
            replace_existing=True,
        )
        scheduler.add_listener(
            _record_job_event, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR | EVENT_JOB_MISSED
        )
        logger.info("Scheduler gestartet (Zeitzone: %s)", settings.timezone)
        logger.info("Nacht-Job 'nightly_session_status_update' registriert (täglich 03:00)")
        logger.info("Stündlicher Job 'hourly_f1_data_fetch' registriert")


def shutdown_scheduler() -> None:
    scheduler = get_scheduler()
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler heruntergefahren")


def schedule_match_monitor(
    match_id: int,
    kickoff_time: datetime,
    duration_minutes: int = 110,
    check_interval_minutes: int = 2,
) -> str:
    estimated_end = kickoff_time + timedelta(minutes=duration_minutes)
    job_id = f"match-{match_id}"
    get_scheduler().add_job(
        _check_match_finished,
        args=[match_id],
        trigger="interval",
        minutes=check_interval_minutes,
        start_date=estimated_end,
        id=job_id,
        replace_existing=True,
    )
    logger.info(
        "Match-Monitor geplant: Job '%s', Start ab %s, Intervall %d min",
        job_id,
        estimated_end.isoformat(),
        check_interval_minutes,
    )
    return job_id


def _check_match_finished(match_id: int) -> None:
    from app.database.session import SessionLocal
    from app.models.match import Match

    FINISHED_STATUSES = {"FT", "AET", "PEN", "finished", "final", "Final"}
    session = SessionLocal()
    try:
        match = session.get(Match, match_id)
        if match is None:
            logger.warning("_check_match_finished: Match %d nicht gefunden", match_id)
            return
        if match.status in FINISHED_STATUSES:
            job_id = f"match-{match_id}"
            try:
                get_scheduler().remove_job(job_id)
            except Exception:
                pass
            logger.info(
                "Match %d ist beendet (Status: %s) — Job '%s' entfernt",
                match_id,
                match.status,
                job_id,
            )
    except Exception as exc:
        logger.exception("Fehler in _check_match_finished für Match %d: %s", match_id, exc)
    finally:
        session.close()


def fetch_missing_f1_data() -> None:
    """Stündlicher Job: Importiert fehlende F1-Sessionergebnisse.

    OpenF1 liefert während einer Session und ca. 1 Stunde danach keine Daten.
    Dieser Job prüft stündlich, welche abgeschlossenen Sessions noch keine
    Ergebnisse in der DB haben, und versucht diese nachzuladen.

    Schwellwert: Session muss mindestens 3 Stunden zurückliegen
    (längste Session ~2h + ~1h OpenF1-Verarbeitungszeit).
    """
    import time as _time

    from app.database.session import SessionLocal
    from app.models import Driver, Race, RaceSession, SessionResult
    from app.services.f1_service import (
        import_f1_drivers,
        import_f1_session_results,
        import_f1_standings,
    )

    _GRACE = timedelta(hours=3)

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)

        # Schwellwert: end_time + 15min (exakt, falls bekannt)
        # Fallback für ältere Sessions ohne end_time: start_time + 3h
        candidates = (
            db.query(RaceSession)
            .filter(
                RaceSession.external_id.isnot(None),
            )
            .all()
        )
        candidates = [
            s for s in candidates
            if (
                # Bevorzuge end_time + 15min falls vorhanden
                (s.end_time is not None and _tz(s.end_time) + _RESULTS_BUFFER < now)
                # Fallback: start_time + 3h
                or (s.end_time is None and s.start_time is not None and _tz(s.start_time) + _GRACE < now)
            )
        ]

        if not candidates:
            logger.info("fetch_missing_f1_data: Keine abgeschlossenen Sessions vorhanden")
            return

        # Fahrer nur importieren wenn noch keine echten F1-Fahrer in der DB sind.
        has_f1_drivers = db.query(Driver).filter(Driver.external_id.isnot(None)).first()
        if not has_f1_drivers:
            logger.info("fetch_missing_f1_data: Keine F1-Fahrer in DB — importiere...")
            import_f1_drivers(db)

        # Status upcoming → completed korrigieren
        status_fixed = 0
        for s in candidates:
            if s.status != "completed":
                s.status = "completed"
                status_fixed += 1
        if status_fixed:
            db.commit()
            logger.info("fetch_missing_f1_data: %d Session(s) auf 'completed' korrigiert", status_fixed)
        status_fixed = 0
        for s in candidates:
            if s.status != "completed":
                s.status = "completed"
                status_fixed += 1
        if status_fixed:
            db.commit()
            logger.info("fetch_missing_f1_data: %d Session(s) auf 'completed' korrigiert", status_fixed)

        # Welche haben noch keine Ergebnisse?
        missing = [
            s for s in candidates
            if db.query(SessionResult).filter(SessionResult.session_id == s.id).count() == 0
        ]

        if not missing:
            logger.info("fetch_missing_f1_data: Alle Sessions haben bereits Ergebnisse")
            return

        logger.info("fetch_missing_f1_data: %d Session(s) ohne Ergebnisse werden abgerufen", len(missing))
        imported = skipped = 0
        for s in missing:
            try:
                result = import_f1_session_results(db, session_key=s.external_id)
                created = result.get("created", 0)
                if created > 0:
                    imported += 1
                    logger.info(
                        "fetch_missing_f1_data: %s (id=%d) — %d Ergebnisse importiert",
                        s.name, s.id, created,
                    )
                else:
                    skipped += 1
                    logger.debug(
                        "fetch_missing_f1_data: %s (id=%d) — noch keine Daten bei OpenF1",
                        s.name, s.id,
                    )
            except Exception as exc:
                skipped += 1
                logger.warning(
                    "fetch_missing_f1_data: Fehler bei %s (id=%d): %s",
                    s.name, s.id, exc,
                )
            _time.sleep(0.5)  # Rate-Limit schonen (OpenF1 Free: 3 req/s, 30 req/min)

        logger.info(
            "fetch_missing_f1_data fertig: %d importiert, %d noch nicht verfügbar",
            imported, skipped,
        )

        # Schritt 2: Standings für jedes Jahr aktualisieren, in dem neue
        # Race-Ergebnisse importiert wurden. Nur Race-Sessions zählen für
        # WM-Punkte; Practice/Qualifying werden übersprungen.
        if imported == 0:
            return

        newly_done_race_ids = {
            s.id for s in missing
            if s.session_type in {"Race", "Sprint"}  # Sprint vergibt ebenfalls WM-Punkte
            and db.query(SessionResult).filter(SessionResult.session_id == s.id).count() > 0
        }
        if not newly_done_race_ids:
            return

        # Jahre der betroffenen Rennen bestimmen
        affected_years: set[int] = set()
        for session in db.query(RaceSession).filter(RaceSession.id.in_(newly_done_race_ids)).all():
            race = db.get(Race, session.race_id)
            if race and race.season:
                try:
                    affected_years.add(int(race.season))
                except ValueError:
                    pass

        for year in affected_years:
            logger.info("fetch_missing_f1_data: Aktualisiere WM-Standings für %s", year)
            try:
                import_f1_standings(db, year=year)
            except Exception as exc:
                logger.warning(
                    "fetch_missing_f1_data: Standings-Update für %s fehlgeschlagen: %s",
                    year, exc,
                )
    except Exception as exc:
        logger.exception("Fehler in fetch_missing_f1_data: %s", exc)
    finally:
        db.close()


def update_session_statuses() -> None:
    """Nächtlicher Job: Setzt Session-Status von 'upcoming' auf 'completed'
    sobald die Session (start_time + Puffer) in der Vergangenheit liegt.

    Läuft täglich um 03:00 Uhr und braucht keine externen API-Aufrufe.
    """
    from app.database.session import SessionLocal
    from app.models.race_session import RaceSession

    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        upcoming = db.query(RaceSession).filter(RaceSession.status == "upcoming").all()
        updated = 0
        for s in upcoming:
            # Bevorzuge end_time + 15min, Fallback auf start_time + 4h
            if s.end_time is not None:
                cutoff = _tz(s.end_time) + _RESULTS_BUFFER
            elif s.start_time is not None:
                cutoff = _tz(s.start_time) + _SESSION_DURATION_BUFFER
            else:
                continue
            if cutoff < now:
                logger.info(
                    "Session-Status geändert: id=%d '%s' upcoming → completed",
                    s.id, s.name,
                )
                s.status = "completed"
                updated += 1
        if updated:
            db.commit()
        logger.info("update_session_statuses: %d Session(s) auf 'completed' gesetzt", updated)
    except Exception as exc:
        logger.exception("Fehler in update_session_statuses: %s", exc)
        db.rollback()
    finally:
        db.close()


def _record_job_event(event: JobExecutionEvent) -> None:
    """APScheduler-Listener: hält eine In-Memory-Historie der letzten Jobläufe."""
    if event.exception:
        status_ = "error"
        error = str(event.exception)
    elif event.code == EVENT_JOB_MISSED:
        status_ = "missed"
        error = None
    else:
        status_ = "success"
        error = None
    _job_history.appendleft(
        {
            "job_id": event.job_id,
            "status": status_,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
    )


def get_job_history() -> list[dict]:
    """Letzte Jobläufe (neueste zuerst), nur solange der Prozess läuft."""
    return list(_job_history)


def list_jobs() -> list[dict]:
    """Alle registrierten Jobs mit Status für die Admin-UI."""
    jobs = []
    for job in get_scheduler().get_jobs():
        jobs.append(
            {
                "id": job.id,
                "name": job.name or job.id,
                "trigger": str(job.trigger),
                "next_run_time": job.next_run_time.isoformat() if job.next_run_time else None,
                # APScheduler setzt next_run_time auf None solange ein Job pausiert ist.
                "paused": job.next_run_time is None,
            }
        )
    return jobs


def pause_job(job_id: str) -> None:
    try:
        get_scheduler().pause_job(job_id)
    except JobLookupError as exc:
        raise ValueError(f"Job '{job_id}' nicht gefunden") from exc


def resume_job(job_id: str) -> None:
    try:
        get_scheduler().resume_job(job_id)
    except JobLookupError as exc:
        raise ValueError(f"Job '{job_id}' nicht gefunden") from exc


def run_job_now(job_id: str) -> None:
    """Lässt einen Job beim nächsten Scheduler-Tick sofort laufen (einmalig, ohne den regulären Zeitplan zu ändern)."""
    scheduler = get_scheduler()
    try:
        scheduler.modify_job(job_id, next_run_time=datetime.now(scheduler.timezone))
    except JobLookupError as exc:
        raise ValueError(f"Job '{job_id}' nicht gefunden") from exc


def scheduler_status() -> dict:
    scheduler = get_scheduler()
    return {
        "running": scheduler.running,
        "enabled": settings.enable_scheduler,
        "timezone": str(scheduler.timezone),
        "job_count": len(scheduler.get_jobs()),
    }
