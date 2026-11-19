"""Hintergrund-Jobs für den WhoScored-Import (gemeinsam genutzt von REST-Admin und Web-UI).

Die Import-Funktionen aus ``football_service`` werden bewusst erst beim Ausführen importiert
(lazy), damit dieses Modul keine Browser-/Scraping-Abhängigkeiten beim App-Start lädt.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.services import background_jobs

# Alle Football-Jobs teilen sich eine Gruppe: es gibt nur eine Browser-Sperre.
FOOTBALL_GROUP = "football"


def run_season_import(
    db: Session,
    league_key: str,
    season_code: str,
    with_details: bool = True,
    max_matches: int | None = None,
) -> dict:
    from app.services import football_service

    return football_service.import_season(
        db, league_key, season_code, with_details=with_details, max_matches=max_matches
    )


def run_match_sync(db: Session, ws_match_id: int, final: bool = False) -> dict:
    from app.services import football_service

    return football_service.sync_match_by_ws_id(db, ws_match_id, final=final)


def resolve_league(league: str):
    """Liefert die Wettbewerbs-Konfiguration; ``ValueError`` mit allen gültigen Schlüsseln sonst."""
    from app.services.football_competitions import COMPETITIONS

    config = COMPETITIONS.get(league)
    if config is None:
        valid = ", ".join(sorted(COMPETITIONS))
        raise ValueError(f"Unbekannte Liga '{league}'. Gültige Werte: {valid}")
    return config


def submit_season_import(
    league: str,
    season: str | None = None,
    with_details: bool = True,
    max_matches: int | None = None,
) -> str:
    """Startet einen Saison-Import im Hintergrund; Job-ID.

    Raises:
        ValueError: unbekannte Liga.
        background_jobs.JobConflictError: es läuft bereits ein Football-Job.
    """
    from app.services.football_competitions import current_season_code

    config = resolve_league(league)
    season_code = season or current_season_code(start_month=config.season_start_month)
    return background_jobs.submit_exclusive(
        FOOTBALL_GROUP,
        f"football-season {league} {season_code}",
        run_season_import,
        league_key=league,
        season_code=season_code,
        with_details=with_details,
        max_matches=max_matches,
    )


def submit_match_sync(ws_match_id: int, final: bool = False) -> str:
    """Startet die Synchronisation eines einzelnen Spiels im Hintergrund; Job-ID."""
    return background_jobs.submit_exclusive(
        FOOTBALL_GROUP,
        f"football-match {ws_match_id}",
        run_match_sync,
        ws_match_id=ws_match_id,
        final=final,
    )
