from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.services import background_jobs, football_jobs
from app.services.f1_service import (
    import_f1_drivers,
    import_f1_races,
    import_f1_session_results,
    import_f1_sessions,
    import_f1_standings,
)
from app.services.nfl_service import (
    import_nfl_games_new,
    import_nfl_standings,
    import_nfl_teams,
)

router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])


@router.post("/import/f1/races")
def admin_import_f1_races(year: int = 2025, db: Session = Depends(get_db)):
    return import_f1_races(db, year=year)


@router.post("/import/f1/drivers")
def admin_import_f1_drivers(session_key: str = "latest", db: Session = Depends(get_db)):
    return import_f1_drivers(db, session_key=session_key)


@router.post("/import/f1/sessions")
def admin_import_f1_sessions(year: int = 2025, db: Session = Depends(get_db)):
    """Importiert F1-Sessions für alle Rennen eines Jahres."""
    return import_f1_sessions(db, year=year)


@router.post("/import/f1/session-results")
def admin_import_f1_session_results(session_key: int, db: Session = Depends(get_db)):
    """Importiert Ergebnisse einer einzelnen F1-Session (via OpenF1 session_key)."""
    return import_f1_session_results(db, session_key=session_key)


@router.post("/import/f1/standings")
def admin_import_f1_standings(year: int = 2025, db: Session = Depends(get_db)):
    """Berechnet F1-Standings aus den vorhandenen Session-Ergebnissen."""
    return import_f1_standings(db, year=year)


@router.post("/import/nfl/teams")
def admin_import_nfl_teams(db: Session = Depends(get_db)):
    return import_nfl_teams(db)


@router.post("/import/nfl/games-new")
def admin_import_nfl_games_new(
    week: int = 1,
    season: int = 2025,
    season_type: str = "reg",
    db: Session = Depends(get_db),
):
    """Importiert NFL-Spiele in die neue nfl_games-Tabelle (per NflTeam-Abkürzung)."""
    return import_nfl_games_new(db, game_week=week, season=season, season_type=season_type)


@router.post("/import/nfl/standings")
def admin_import_nfl_standings(season: int = 2025, db: Session = Depends(get_db)):
    """Importiert NFL-Standings (W/L/D) für eine Saison."""
    return import_nfl_standings(db, season=season)


@router.post("/import/football/season", status_code=202)
def admin_import_football_season(
    league: str = "GER-Bundesliga",
    season: Optional[str] = None,
    with_details: bool = True,
    max_matches: Optional[int] = None,
):
    """Startet den WhoScored-Import einer Saison im Hintergrund (Dauer: Minuten).

    Ohne ``season`` wird die aktuelle Saison der Liga verwendet. Fortschritt über ``/admin/jobs``.
    """
    try:
        job_id = football_jobs.submit_season_import(
            league, season, with_details=with_details, max_matches=max_matches
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except background_jobs.JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.post("/import/football/match/{ws_match_id}", status_code=202)
def admin_import_football_match(ws_match_id: int, final: bool = False):
    """Synchronisiert ein einzelnes Spiel (WhoScored-Match-ID) im Hintergrund."""
    try:
        job_id = football_jobs.submit_match_sync(ws_match_id, final=final)
    except background_jobs.JobConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": job_id}


@router.get("/jobs")
def admin_list_jobs(limit: int = 50):
    """Hintergrund-Jobs (neueste zuerst)."""
    return background_jobs.list_jobs(limit=limit)


@router.get("/jobs/{job_id}")
def admin_get_job(job_id: str):
    job = background_jobs.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job {job_id} nicht gefunden")
    return job
