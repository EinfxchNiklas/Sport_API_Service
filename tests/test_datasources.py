import pytest
import respx
from httpx import Response

import app.config as config_module
from app.services.datasources import OpenF1Client, Tank01Client


# ---------------------------------------------------------------------------
# OpenF1
# ---------------------------------------------------------------------------

@respx.mock
def test_openf1_fetch_races():
    respx.get("https://api.openf1.org/v1/meetings").mock(
        return_value=Response(
            200,
            json=[
                {
                    "meeting_official_name": "Bahrain Grand Prix",
                    "meeting_name": "Bahrain",
                    "date_start": "2025-03-02T15:00:00+00:00",
                }
            ],
        )
    )
    client = OpenF1Client()
    races = client.fetch_races(2025)
    assert len(races) == 1
    race = races[0]
    assert race["season"] == "2025"
    assert race["name"] == "Bahrain Grand Prix"
    assert race["date"] == "2025-03-02T15:00:00+00:00"
    assert race["status"] == "scheduled"


@respx.mock
def test_openf1_fetch_drivers_deduplication():
    respx.get("https://api.openf1.org/v1/drivers").mock(
        return_value=Response(
            200,
            json=[
                {"driver_number": 1, "full_name": "Max Verstappen", "team_name": "Red Bull Racing"},
                {"driver_number": 1, "full_name": "Max Verstappen", "team_name": "Red Bull Racing"},
                {"driver_number": 44, "full_name": "Lewis Hamilton", "team_name": "Ferrari"},
            ],
        )
    )
    client = OpenF1Client()
    drivers = client.fetch_drivers("latest")
    assert len(drivers) == 2
    assert drivers[0] == {"name": "Max Verstappen", "team": "Red Bull Racing", "number": 1, "abbreviation": None, "country": None, "team_color": None, "external_id": 1}
    assert drivers[1] == {"name": "Lewis Hamilton", "team": "Ferrari", "number": 44, "abbreviation": None, "country": None, "team_color": None, "external_id": 44}


@respx.mock
def test_openf1_fetch_drivers_fallback_name():
    respx.get("https://api.openf1.org/v1/drivers").mock(
        return_value=Response(
            200,
            json=[
                {
                    "driver_number": 16,
                    "first_name": "Charles",
                    "last_name": "Leclerc",
                    "team_name": "Ferrari",
                },
            ],
        )
    )
    client = OpenF1Client()
    drivers = client.fetch_drivers()
    assert drivers[0]["name"] == "Charles Leclerc"


# ---------------------------------------------------------------------------
# Tank01
# ---------------------------------------------------------------------------

@respx.mock
def test_tank01_fetch_nfl_teams(monkeypatch):
    host = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
    monkeypatch.setattr(config_module.settings, "tank01_key", "test-key")
    monkeypatch.setattr(config_module.settings, "tank01_host", host)
    respx.get(f"https://{host}/getNFLTeams").mock(
        return_value=Response(
            200,
            json={
                "body": [
                    {
                        "teamCity": "Kansas City",
                        "teamName": "Chiefs",
                        "conferenceAbv": "AFC",
                        "division": "AFC West",
                    }
                ]
            },
        )
    )
    client = Tank01Client()
    teams = client.fetch_nfl_teams()
    assert len(teams) == 1
    assert teams[0] == {
        "name": "Kansas City Chiefs",
        "conference": "AFC",
        "division": "AFC West",
        "abbreviation": None,
        "city": "Kansas City",
        "logo_url": None,
        "external_id": None,
    }


@respx.mock
def test_tank01_fetch_games(monkeypatch):
    host = "tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com"
    monkeypatch.setattr(config_module.settings, "tank01_key", "test-key")
    monkeypatch.setattr(config_module.settings, "tank01_host", host)
    respx.get(f"https://{host}/getNFLGamesForWeek").mock(
        return_value=Response(
            200,
            json={
                "body": [
                    {
                        "home": "Kansas City Chiefs",
                        "away": "Baltimore Ravens",
                        "gameTime": "2025-09-07T13:00:00",
                        "gameStatus": "Scheduled",
                        "homePts": None,
                        "awayPts": None,
                    }
                ]
            },
        )
    )
    client = Tank01Client()
    games = client.fetch_games(game_week=1, season=2025)
    assert len(games) == 1
    assert games[0] == {
        "home_team": "Kansas City Chiefs",
        "away_team": "Baltimore Ravens",
        "kickoff_time": "2025-09-07T13:00:00",
        "status": "Scheduled",
        "home_score": None,
        "away_score": None,
        "external_id": None,
        "season": 2025,
        "season_type": "reg",
        "week": 1,
    }


def test_tank01_missing_key_raises(monkeypatch):
    monkeypatch.setattr(config_module.settings, "tank01_key", "")
    client = Tank01Client()
    with pytest.raises(RuntimeError, match="TANK01_KEY"):
        client.fetch_nfl_teams()
    with pytest.raises(RuntimeError, match="TANK01_KEY"):
        client.fetch_games()
