import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models import Base, Driver, NflTeam, Race
from app.services.datasources import OpenF1Client, Tank01Client
from app.services.f1_service import import_f1_drivers, import_f1_races
from app.services.nfl_service import import_nfl_teams


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


# ─── F1 Races ────────────────────────────────────────────────────────────────

_F1_RACES = [{"season": "2025", "name": "Test GP", "date": None, "status": "scheduled"}]


def test_import_f1_races_creates(db, monkeypatch):
    monkeypatch.setattr(OpenF1Client, "fetch_races", lambda self, year=2025: list(_F1_RACES))
    result = import_f1_races(db)
    assert result["created"] == 1
    assert result["updated"] == 0
    assert db.query(Race).count() == 1


def test_import_f1_races_no_duplicate(db, monkeypatch):
    monkeypatch.setattr(OpenF1Client, "fetch_races", lambda self, year=2025: list(_F1_RACES))
    import_f1_races(db)
    result = import_f1_races(db)
    assert result["created"] == 0
    assert result["updated"] == 1
    assert db.query(Race).count() == 1


# ─── F1 Drivers ──────────────────────────────────────────────────────────────

_F1_DRIVERS = [{"name": "Max Verstappen", "team": "Red Bull Racing", "number": 1}]


def test_import_f1_drivers_creates(db, monkeypatch):
    monkeypatch.setattr(
        OpenF1Client,
        "fetch_drivers",
        lambda self, session_key="latest": list(_F1_DRIVERS),
    )
    result = import_f1_drivers(db)
    assert result["created"] == 1
    assert db.query(Driver).count() == 1


def test_import_f1_drivers_no_duplicate(db, monkeypatch):
    monkeypatch.setattr(
        OpenF1Client,
        "fetch_drivers",
        lambda self, session_key="latest": list(_F1_DRIVERS),
    )
    import_f1_drivers(db)
    result = import_f1_drivers(db)
    assert result["created"] == 0
    assert result["updated"] == 1
    assert db.query(Driver).count() == 1


# ─── NFL Teams ────────────────────────────────────────────────────────────────

_NFL_TEAMS = [
    {"name": "Kansas City Chiefs", "conference": "AFC", "division": "West"},
    {"name": "San Francisco 49ers", "conference": "NFC", "division": "West"},
]


def test_import_nfl_teams_creates(db, monkeypatch):
    monkeypatch.setattr(Tank01Client, "fetch_nfl_teams", lambda self: [dict(t) for t in _NFL_TEAMS])
    result = import_nfl_teams(db)
    assert result["created"] == 2
    assert db.query(NflTeam).count() == 2


def test_import_nfl_teams_no_duplicate(db, monkeypatch):
    monkeypatch.setattr(Tank01Client, "fetch_nfl_teams", lambda self: [dict(t) for t in _NFL_TEAMS])
    import_nfl_teams(db)
    result = import_nfl_teams(db)
    assert result["created"] == 0
    assert result["updated"] == 2
    assert db.query(NflTeam).count() == 2
