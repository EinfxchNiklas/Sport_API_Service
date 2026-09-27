from __future__ import annotations

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.api.deps import get_db, require_admin
from app.models import Competition, Driver, Match, NflGame, NflTeam, Race, RaceSession, Team
from app.schedulers.scheduler import (
    get_job_history,
    list_jobs,
    pause_job,
    resume_job,
    run_job_now,
    scheduler_status,
)
from app.services.f1_service import (
    import_f1_drivers,
    import_f1_races,
    import_f1_session_results,
    import_f1_sessions,
    import_f1_standings,
)
from app.services.football_service import import_bundesliga, import_football_competition
from app.services.nfl_service import (
    import_nfl_games,
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


@router.post("/actions/bundesliga")
def action_bundesliga(season: int = 2025, league_id: int = 78, db: Session = Depends(get_db)):
    return _run_action(import_bundesliga, db=db, season=season, league_id=league_id)


@router.post("/actions/football")
def action_football(league_id: int = 78, season: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_football_competition, db=db, league_id=league_id, season=season)


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


@router.post("/actions/nfl-games")
def action_nfl_games(
    game_week: int = 1, season: int = 2025, season_type: str = "reg", db: Session = Depends(get_db)
):
    return _run_action(
        import_nfl_games, db=db, game_week=game_week, season=season, season_type=season_type
    )


@router.post("/actions/nfl-games-new")
def action_nfl_games_new(
    week: int = 1, season: int = 2025, season_type: str = "reg", db: Session = Depends(get_db)
):
    return _run_action(
        import_nfl_games_new, db=db, game_week=week, season=season, season_type=season_type
    )


@router.post("/actions/nfl-standings")
def action_nfl_standings(season: int = 2025, db: Session = Depends(get_db)):
    return _run_action(import_nfl_standings, db=db, season=season)
