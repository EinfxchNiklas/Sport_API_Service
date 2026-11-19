import sys
import threading
import types

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import app.services as services_pkg
from app.config import settings
from app.database.session import get_db
from app.models import Base
from app.services import background_jobs
from app.services.football_competitions import current_season_code
from main import app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

HEADERS = {"X-API-Key": settings.admin_api_key}


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolated_jobs(monkeypatch):
    """Jobs pro Test zurücksetzen und eigene Test-Sessions statt der Produktions-DB verwenden."""
    monkeypatch.setattr(background_jobs, "SessionLocal", TestingSessionLocal)
    background_jobs.clear()
    yield
    background_jobs.clear()


def stub_service(monkeypatch, **funcs):
    """Ersetzt app.services.football_service durch ein Stub-Modul (unabhängig davon, ob es existiert)."""
    module = types.ModuleType("app.services.football_service")
    for name, fn in funcs.items():
        setattr(module, name, fn)
    monkeypatch.setitem(sys.modules, "app.services.football_service", module)
    monkeypatch.setattr(services_pkg, "football_service", module, raising=False)
    return module


# ── Auth ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "method, url",
    [
        ("post", "/api/v1/admin/import/football/season"),
        ("post", "/api/v1/admin/import/football/match/123"),
        ("get", "/api/v1/admin/jobs"),
        ("get", "/api/v1/admin/jobs/abc"),
        ("get", "/admin/api/jobs"),
        ("post", "/admin/api/actions/football-season"),
        ("post", "/admin/api/actions/football-match?ws_match_id=1"),
    ],
)
def test_football_admin_requires_auth(client, method, url):
    assert getattr(client, method)(url).status_code == 401


# ── REST-Admin ───────────────────────────────────────────────────────────────

def test_season_import_runs_in_background(client, monkeypatch):
    calls = []

    def fake_import_season(db, league_key, season_code, with_details=True, client=None, max_matches=None):
        calls.append((league_key, season_code, with_details, max_matches))
        assert db is not None
        return {"matches": 3}

    stub_service(monkeypatch, import_season=fake_import_season)
    resp = client.post(
        "/api/v1/admin/import/football/season",
        params={"league": "GER-Bundesliga", "season": "2526", "with_details": "false", "max_matches": 2},
        headers=HEADERS,
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    background_jobs.wait(job_id, timeout=10)

    job = client.get(f"/api/v1/admin/jobs/{job_id}", headers=HEADERS).json()
    assert job["status"] == "success"
    assert job["result"] == {"matches": 3}
    assert job["error"] is None
    assert job["started_at"] and job["finished_at"]
    assert calls == [("GER-Bundesliga", "2526", False, 2)]

    listing = client.get("/api/v1/admin/jobs", headers=HEADERS).json()
    assert [j["id"] for j in listing] == [job_id]


def test_season_import_defaults_to_current_season(client, monkeypatch):
    calls = []

    def fake_import_season(db, league_key, season_code, with_details=True, client=None, max_matches=None):
        calls.append((league_key, season_code, with_details, max_matches))
        return {}

    stub_service(monkeypatch, import_season=fake_import_season)
    resp = client.post("/api/v1/admin/import/football/season", headers=HEADERS)
    assert resp.status_code == 202
    background_jobs.wait(resp.json()["job_id"], timeout=10)
    assert calls == [("GER-Bundesliga", current_season_code(), True, None)]


def test_season_import_error_is_stored(client, monkeypatch):
    def failing(db, league_key, season_code, with_details=True, client=None, max_matches=None):
        raise RuntimeError("Chrome nicht gefunden")

    stub_service(monkeypatch, import_season=failing)
    job_id = client.post("/api/v1/admin/import/football/season", headers=HEADERS).json()["job_id"]
    background_jobs.wait(job_id, timeout=10)
    job = client.get(f"/api/v1/admin/jobs/{job_id}", headers=HEADERS).json()
    assert job["status"] == "error"
    assert "Chrome nicht gefunden" in job["error"]
    assert job["finished_at"]


def test_season_import_invalid_league_422(client, monkeypatch):
    stub_service(monkeypatch, import_season=lambda *a, **k: {})
    resp = client.post(
        "/api/v1/admin/import/football/season", params={"league": "XXX-Liga"}, headers=HEADERS
    )
    assert resp.status_code == 422
    assert "GER-Bundesliga" in resp.json()["detail"]
    assert background_jobs.list_jobs() == []


def test_match_sync_runs_in_background(client, monkeypatch):
    calls = []

    def fake_sync(db, ws_match_id, final=False):
        calls.append((ws_match_id, final))
        return {"status": "ok"}

    stub_service(monkeypatch, sync_match_by_ws_id=fake_sync)
    resp = client.post(
        "/api/v1/admin/import/football/match/1821234", params={"final": "true"}, headers=HEADERS
    )
    assert resp.status_code == 202
    job_id = resp.json()["job_id"]
    background_jobs.wait(job_id, timeout=10)
    assert calls == [(1821234, True)]
    assert client.get(f"/api/v1/admin/jobs/{job_id}", headers=HEADERS).json()["status"] == "success"


def test_concurrent_football_job_rejected_409(client, monkeypatch):
    started = threading.Event()
    release = threading.Event()

    def slow_import(db, league_key, season_code, with_details=True, client=None, max_matches=None):
        started.set()
        release.wait(timeout=10)
        return {"done": True}

    stub_service(monkeypatch, import_season=slow_import, sync_match_by_ws_id=lambda db, ws_match_id, final=False: {})
    first = client.post("/api/v1/admin/import/football/season", headers=HEADERS)
    assert first.status_code == 202
    assert started.wait(timeout=10)

    running = client.get(f"/api/v1/admin/jobs/{first.json()['job_id']}", headers=HEADERS).json()
    assert running["status"] == "running"

    assert client.post("/api/v1/admin/import/football/season", headers=HEADERS).status_code == 409
    assert client.post("/api/v1/admin/import/football/match/5", headers=HEADERS).status_code == 409

    release.set()
    background_jobs.wait(first.json()["job_id"], timeout=10)

    # Nach Abschluss ist wieder ein Import möglich.
    again = client.post("/api/v1/admin/import/football/match/5", headers=HEADERS)
    assert again.status_code == 202
    background_jobs.wait(again.json()["job_id"], timeout=10)


def test_unknown_job_404(client):
    assert client.get("/api/v1/admin/jobs/doesnotexist", headers=HEADERS).status_code == 404


# ── Web-UI-API ───────────────────────────────────────────────────────────────

def test_web_action_football_season_returns_job_id(client, monkeypatch):
    calls = []

    def fake_import_season(db, league_key, season_code, with_details=True, client=None, max_matches=None):
        calls.append((league_key, season_code, with_details, max_matches))
        return {"ok": 1}

    stub_service(monkeypatch, import_season=fake_import_season)
    resp = client.post(
        "/admin/api/actions/football-season",
        params={"league": "GER-2. Bundesliga", "season": "", "with_details": "true"},
        headers=HEADERS,
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    job_id = data["result"]["job_id"]
    background_jobs.wait(job_id, timeout=10)
    assert calls[0][0] == "GER-2. Bundesliga"
    assert calls[0][1] == current_season_code()

    jobs = client.get("/admin/api/jobs", headers=HEADERS).json()["jobs"]
    assert jobs[0]["id"] == job_id
    assert jobs[0]["status"] == "success"


def test_web_action_football_season_invalid_league(client):
    resp = client.post(
        "/admin/api/actions/football-season", params={"league": "XXX"}, headers=HEADERS
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is False
    assert "GER-Bundesliga" in data["error"]


def test_web_action_football_match_and_conflict(client, monkeypatch):
    release = threading.Event()

    def slow_sync(db, ws_match_id, final=False):
        release.wait(timeout=10)
        return {"ws_match_id": ws_match_id}

    stub_service(monkeypatch, sync_match_by_ws_id=slow_sync)
    first = client.post(
        "/admin/api/actions/football-match", params={"ws_match_id": 42}, headers=HEADERS
    ).json()
    assert first["ok"] is True

    second = client.post(
        "/admin/api/actions/football-match", params={"ws_match_id": 43}, headers=HEADERS
    ).json()
    assert second["ok"] is False

    release.set()
    background_jobs.wait(first["result"]["job_id"], timeout=10)
    job = background_jobs.get_job(first["result"]["job_id"])
    assert job["status"] == "success"
    assert job["result"] == {"ws_match_id": 42}


def test_web_overview_counts_include_football_tables(client):
    counts = client.get("/admin/api/overview", headers=HEADERS).json()["counts"]
    for label in ("Wettbewerbe", "Teams", "Spiele", "Spieler", "Einsätze", "Fehlende Spieler"):
        assert label in counts


def test_dashboard_shows_football_cards(client):
    client.post("/admin/login", data={"api_key": settings.admin_api_key}, follow_redirects=False)
    resp = client.get("/admin")
    client.post("/admin/logout", follow_redirects=False)
    assert resp.status_code == 200
    assert "Fußball (WhoScored)" in resp.text
    assert "GER-Bundesliga" in resp.text
    assert current_season_code() in resp.text
    assert "Hintergrund-Jobs" in resp.text


# ── background_jobs ──────────────────────────────────────────────────────────

def test_background_jobs_submit_and_list():
    def work(db, x):
        return {"x": x}

    job_id = background_jobs.submit("test-job", work, x=5)
    background_jobs.wait(job_id, timeout=10)
    job = background_jobs.get_job(job_id)
    assert job["name"] == "test-job"
    assert job["status"] == "success"
    assert job["result"] == {"x": 5}
    assert job["started_at"].tzinfo is not None
    assert background_jobs.list_jobs(limit=1)[0]["id"] == job_id
    assert background_jobs.get_job("missing") is None
    assert background_jobs.has_active("football") is False
