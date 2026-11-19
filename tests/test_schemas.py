import types
from datetime import datetime

from app.schemas import (
    DriverRead,
    NflTeamRead,
    RaceRead,
)


def make_obj(**kwargs):
    return types.SimpleNamespace(**kwargs)


def test_driver_read():
    obj = make_obj(id=1, name="Max Verstappen", team="Red Bull", number=1)
    schema = DriverRead.model_validate(obj)
    assert schema.id == 1
    assert schema.name == "Max Verstappen"
    assert schema.team == "Red Bull"
    assert schema.number == 1


def test_driver_read_optional_none():
    obj = make_obj(id=2, name="Some Driver", team=None, number=None)
    schema = DriverRead.model_validate(obj)
    assert schema.team is None
    assert schema.number is None


def test_race_read():
    race_date = datetime(2025, 3, 16, 15, 0, 0)
    obj = make_obj(id=1, season="2025", name="Bahrain GP", date=race_date, status="finished")
    schema = RaceRead.model_validate(obj)
    assert schema.id == 1
    assert schema.season == "2025"
    assert schema.name == "Bahrain GP"
    assert schema.date == race_date
    assert schema.status == "finished"


def test_race_read_optional_none():
    obj = make_obj(id=2, season=None, name="Unknown Race", date=None, status=None)
    schema = RaceRead.model_validate(obj)
    assert schema.season is None
    assert schema.date is None
    assert schema.status is None


def test_nfl_team_read():
    obj = make_obj(id=1, name="Kansas City Chiefs", conference="AFC", division="West")
    schema = NflTeamRead.model_validate(obj)
    assert schema.id == 1
    assert schema.name == "Kansas City Chiefs"
    assert schema.conference == "AFC"
    assert schema.division == "West"


def test_nfl_team_read_optional_none():
    obj = make_obj(id=2, name="Some Team", conference=None, division=None)
    schema = NflTeamRead.model_validate(obj)
    assert schema.conference is None
    assert schema.division is None
