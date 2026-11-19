from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models import (
    Appearance,
    Competition,
    Driver,
    Match,
    MissingPlayer,
    NflGame,
    NflTeam,
    Player,
    Race,
    RaceSession,
    Team,
)
from app.schedulers.scheduler import (
    get_job_history,
    list_jobs,
    pause_job,
    resume_job,
    run_job_now,
    scheduler_status,
)
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
from app.web.metadata import get_architecture_graph, get_regenerated_graph

router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)])

_COUNT_TABLES = [
    ("Wettbewerbe", Competition),
    ("Teams", Team),
    ("Spiele", Match),
    ("Spieler", Player),
    ("Einsätze", Appearance),
    ("Fehlende Spieler", MissingPlayer),
    ("F1-Fahrer", Driver),
    ("F1-Rennen", Race),
    ("F1-Sessions", RaceSession),
    ("NFL-Teams", NflTeam),
    ("NFL-Spiele", NflGame),
]


@router.get("/overview")
def api_overview(db: Session = Depends(get_db)):
    counts = {label: db.query(model).count() for label, model in _COUNT_TABLES}
    return {"scheduler": scheduler_status(), "counts": counts}


@router.get("/schedulers")
def api_schedulers():
    return {"jobs": list_jobs(), "history": get_job_history(), "status": scheduler_status()}


@router.post("/schedulers/{job_id}/pause")
def api_pause_job(job_id: str):
    try:
        pause_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/schedulers/{job_id}/resume")
def api_resume_job(job_id: str):
    try:
        resume_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/schedulers/{job_id}/run")
def api_run_job(job_id: str):
    try:
        run_job_now(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}


@router.get("/architecture")
def api_architecture():
    return get_architecture_graph()


@router.post("/architecture/regenerate")
def api_architecture_regenerate(request: Request):
    return get_regenerated_graph(request.app)


def _run_action(fn, **kwargs):
    try:
        result = fn(**kwargs)
        return {"ok": True, "result": result}
    except Exception as exc:
        # Fehler dem Admin im UI anzeigen statt als 500 zu verschlucken.
        return {"ok": False, "error": str(exc)}


@router.post("/actions/f1-races")
def action_f1_races(year: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_f1_races, db=db, year=year)


@router.post("/actions/f1-drivers")
def action_f1_drivers(session_key: str = "latest", db: Session = Depends(get_db)):
    return _run_action(import_f1_drivers, db=db, session_key=session_key)


@router.post("/actions/f1-sessions")
def action_f1_sessions(year: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_f1_sessions, db=db, year=year)


@router.post("/actions/f1-session-results")
def action_f1_session_results(payload: dict = Body(...), db: Session = Depends(get_db)):
    session_key = payload.get("session_key")
    if session_key in (None, ""):
        raise HTTPException(status_code=422, detail="session_key erforderlich")
    return _run_action(import_f1_session_results, db=db, session_key=int(session_key))


@router.post("/actions/f1-standings")
def action_f1_standings(year: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_f1_standings, db=db, year=year)


@router.post("/actions/nfl-teams")
def action_nfl_teams(db: Session = Depends(get_db)):
    return _run_action(import_nfl_teams, db=db)


@router.post("/actions/nfl-games-new")
def action_nfl_games_new(
    week: int = 1, season: int = 2025, season_type: str = "reg", db: Session = Depends(get_db)
):
    return _run_action(
        import_nfl_games_new, db=db, game_week=week, season=season, season_type=season_type
    )


@router.get("/jobs")
def api_jobs(limit: int = 50):
    return {"jobs": background_jobs.list_jobs(limit=limit)}


def _submit_job(submit, **kwargs):
    """Startet einen Hintergrund-Job; Fehler (ungültige Liga, laufender Job) landen im UI-Format."""
    try:
        return {"ok": True, "result": {"job_id": submit(**kwargs)}}
    except (ValueError, background_jobs.JobConflictError) as exc:
        return {"ok": False, "error": str(exc)}


@router.post("/actions/football-season")
def action_football_season(
    league: str = "GER-Bundesliga",
    season: Optional[str] = None,
    with_details: bool = True,
    max_matches: Optional[int] = None,
):
    return _submit_job(
        football_jobs.submit_season_import,
        league=league,
        season=season or None,
        with_details=with_details,
        max_matches=max_matches,
    )


@router.post("/actions/football-match")
def action_football_match(ws_match_id: int, final: bool = False):
    return _submit_job(football_jobs.submit_match_sync, ws_match_id=ws_match_id, final=final)


@router.post("/actions/nfl-standings")
def action_nfl_standings(season: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_nfl_standings, db=db, season=season)
