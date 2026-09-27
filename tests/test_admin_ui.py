import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.session import get_db
from app.models import Base
from main import app

SQLALCHEMY_TEST_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


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


# ── Login-Seite & Zugriffsschutz ─────────────────────────────────────────────

def test_login_page_loads(client):
    resp = client.get("/admin/login")
    assert resp.status_code == 200
    assert "API-Key" in resp.text


def test_dashboard_redirects_without_login(client):
    resp = client.get("/admin", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login"


def test_schedulers_page_redirects_without_login(client):
    resp = client.get("/admin/schedulers", follow_redirects=False)
    assert resp.status_code == 303


def test_login_with_wrong_key_shows_error(client):
    resp = client.post("/admin/login", data={"api_key": "wrong"}, follow_redirects=False)
    assert resp.status_code == 401
    assert "Ungültiger API-Key" in resp.text


def test_login_with_correct_key_grants_access(client):
    resp = client.post(
        "/admin/login", data={"api_key": settings.admin_api_key}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"

    dashboard_resp = client.get("/admin")
    assert dashboard_resp.status_code == 200
    assert "Dashboard" in dashboard_resp.text

    # Logout entfernt den Zugriff wieder.
    logout_resp = client.post("/admin/logout", follow_redirects=False)
    assert logout_resp.status_code == 303
    assert client.get("/admin", follow_redirects=False).status_code == 303


# ── JSON-APIs ─────────────────────────────────────────────────────────────────

def test_api_requires_auth(client):
    resp = client.get("/admin/api/schedulers")
    assert resp.status_code == 401


def test_api_schedulers_with_header_key(client):
    resp = client.get("/admin/api/schedulers", headers={"X-API-Key": settings.admin_api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert set(data.keys()) == {"jobs", "history", "status"}


def test_api_overview_with_header_key(client):
    resp = client.get("/admin/api/overview", headers={"X-API-Key": settings.admin_api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert "scheduler" in data
    assert "counts" in data


def test_api_architecture_shape(client):
    resp = client.get("/admin/api/architecture", headers={"X-API-Key": settings.admin_api_key})
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"]
    assert data["edges"]
    types = {n["data"]["type"] for n in data["nodes"]}
    assert {"endpoint", "service", "datasource", "table"}.issubset(types)


def test_api_architecture_regenerate(client):
    resp = client.post(
        "/admin/api/architecture/regenerate", headers={"X-API-Key": settings.admin_api_key}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["nodes"]


def test_api_scheduler_pause_unknown_job_returns_404(client):
    resp = client.post(
        "/admin/api/schedulers/does-not-exist/pause",
        headers={"X-API-Key": settings.admin_api_key},
    )
    assert resp.status_code == 404


def test_api_action_nfl_teams_invokes_service(client, monkeypatch):
    monkeypatch.setattr(
        "app.web.api.import_nfl_teams", lambda db: {"created": 1, "updated": 0}
    )
    resp = client.post(
        "/admin/api/actions/nfl-teams", headers={"X-API-Key": settings.admin_api_key}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"] == {"created": 1, "updated": 0}
