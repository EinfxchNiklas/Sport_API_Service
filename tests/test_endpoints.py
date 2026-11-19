from datetime import datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.database.session import get_db
from app.models import Base, Driver, NflGame, NflTeam, Race
from main import app

SQLALCHEMY_TEST_URL = "sqlite:///:memory:"

engine = create_engine(
    SQLALCHEMY_TEST_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)


def seed_db(db: Session):
    # F1
    race = Race(name="Bahrain Grand Prix", season="2025", status="finished")
    driver = Driver(name="Max Verstappen", team="Red Bull", number=1)
    db.add_all([race, driver])

    # NFL
    chiefs = NflTeam(name="Kansas City Chiefs", conference="AFC", division="West")
    bills = NflTeam(name="Buffalo Bills", conference="AFC", division="East")
    db.add_all([chiefs, bills])
    db.flush()

    db.add(
        NflGame(
            season=datetime.now().year,
            season_type="reg",
            week=1,
            home_team_id=chiefs.id,
            away_team_id=bills.id,
            status="Final",
            home_score=27,
            away_score=24,
        )
    )

    db.commit()


@pytest.fixture(scope="module")
def client():
    Base.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    seed_db(db)
    db.close()

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


# ── F1 ───────────────────────────────────────────────────────────────────────

def test_f1_races(client):
    resp = client.get("/api/v1/f1/races")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Bahrain Grand Prix"


def test_f1_drivers(client):
    resp = client.get("/api/v1/f1/drivers")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Max Verstappen"


# ── NFL ───────────────────────────────────────────────────────────────────────

def test_nfl_teams(client):
    resp = client.get("/api/v1/nfl/teams")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["name"] == "Kansas City Chiefs"


def test_nfl_games(client):
    resp = client.get("/api/v1/nfl/games")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    assert data[0]["home_score"] == 27


def test_nfl_games_with_season(client):
    resp = client.get(f"/api/v1/nfl/games?season={datetime.now().year}&week=1")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["week"] == 1


# ── Admin auth ────────────────────────────────────────────────────────────────

def test_admin_no_key_returns_401(client):
    resp = client.post("/api/v1/admin/import/nfl/teams")
    assert resp.status_code == 401


def test_admin_with_key_returns_200(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.v1.admin.import_nfl_teams",
        lambda db: {"created": 1, "updated": 0},
    )
    resp = client.post(
        "/api/v1/admin/import/nfl/teams",
        headers={"X-API-Key": settings.admin_api_key},
    )
    assert resp.status_code == 200
    assert resp.json() == {"created": 1, "updated": 0}
