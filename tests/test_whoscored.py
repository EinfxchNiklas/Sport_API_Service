"""Tests für WhoScored-Parser und -Client (ohne Netzwerk, ohne Chrome).

Die JSON-/HTML-Fixtures unter tests/fixtures/whoscored stammen (getrimmt) aus echten
WhoScored-Antworten (Bundesliga 2026/27, abgerufen 19.11.2026).
"""

import copy
import io
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

import app.services.datasources.whoscored as ws_module
from app.services.datasources.whoscored import (
    WHOSCORED_BROWSER_LOCK,
    BrowserBusyError,
    WhoScoredClient,
    WhoScoredError,
    normalize_season_code,
)
from app.services.datasources.whoscored_parsers import (
    DERIVED_STAT_KEYS,
    aggregate_stat,
    map_fixture_status,
    parse_fixture,
    parse_match_centre,
    parse_missing_players_html,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "whoscored"
BERLIN = ZoneInfo("Europe/Berlin")


def _load_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _load_text(name: str) -> str:
    return (FIXTURE_DIR / name).read_text(encoding="utf-8")


@pytest.fixture
def raw_fixtures() -> dict[int, dict]:
    data = _load_json("fixtures_month.json")
    return {m["id"]: m for t in data["tournaments"] for m in t["matches"]}


@pytest.fixture
def mc_own_goal() -> dict:
    return _load_json("match_centre_own_goal.json")


@pytest.fixture
def mc_penalty() -> dict:
    return _load_json("match_centre_penalty.json")


# Echtes Pokal-Spiel (Elfmeterschießen), Felder gekürzt (DFB-Pokal 2025/26, 1. Runde).
CUP_PEN_FIXTURE = {
    "stageId": 24480,
    "id": 1902381,
    "status": 6,
    "startTime": "2025-08-16T14:30:00",
    "homeTeamId": 5533,
    "homeTeamName": "FV Illertissen",
    "awayTeamId": 137,
    "awayTeamName": "Nuernberg",
    "hasPreview": False,
    "elapsed": "PEN",
    "homeTeamCountryCode": "de",
    "awayTeamCountryCode": "de",
    "homeTeamCountryName": "Germany",
    "awayTeamCountryName": "Germany",
    "startTimeUtc": "2025-08-16T13:30:00Z",
    "homeScore": 3,
    "awayScore": 3,
    "period": 0,
    "homeExtratimeScore": 3,
    "awayExtratimeScore": 3,
    "homePenaltyScore": 6,
    "awayPenaltyScore": 5,
    "startedAtUtc": "2025-08-16T13:33:23Z",
    "firstHalfEndedAtUtc": "2025-08-16T14:24:26Z",
    "secondHalfStartedAtUtc": "2025-08-16T14:41:21Z",
}


# ---------------------------------------------------------------------------
# aggregate_stat
# ---------------------------------------------------------------------------

def test_aggregate_stat_sums_counting_stats():
    assert aggregate_stat("passesTotal", {"1": 2, "5": 3, "90": 1}) == 6.0


def test_aggregate_stat_ratings_uses_highest_minute():
    # Schlüssel sind Strings; "9" < "10" numerisch, nicht lexikografisch
    assert aggregate_stat("ratings", {"9": 6.1, "10": 6.9, "2": 5.0}) == 6.9


@pytest.mark.parametrize("key", sorted(DERIVED_STAT_KEYS))
def test_aggregate_stat_excludes_derived_keys(key):
    assert aggregate_stat(key, {"1": 100, "2": 50}) is None


@pytest.mark.parametrize("value", [None, [], {}, ["1", "2"], "abc", {"1": "x"}, {"1": None}, {"1": True}])
def test_aggregate_stat_ignores_invalid_values(value):
    assert aggregate_stat("touches", value) is None


def test_aggregate_stat_skips_non_numeric_entries():
    assert aggregate_stat("touches", {"1": 2, "2": "x", "3": 4}) == 6.0


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def test_parse_fixture_finished(raw_fixtures):
    fx = parse_fixture(raw_fixtures[1995458])
    assert fx["ws_match_id"] == 1995458
    assert fx["ws_stage_id"] == 25666
    assert fx["status"] == "finished"
    # 14:30 UTC am 01.11.2026 = 15:30 MEZ
    assert fx["kickoff_time"] == datetime(2026, 11, 1, 15, 30, tzinfo=BERLIN)
    assert fx["kickoff_time"].utcoffset().total_seconds() == 3600
    assert fx["home"] == {
        "ws_team_id": 796,
        "name": "Union Berlin",
        "country_code": "de",
        "country_name": "Germany",
    }
    assert fx["away"]["ws_team_id"] == 282
    assert (fx["home_score"], fx["away_score"]) == (1, 1)
    assert fx["et_home_score"] is None and fx["pen_away_score"] is None
    assert fx["started_at"] == datetime(2026, 11, 1, 15, 30, 8, tzinfo=BERLIN)
    assert fx["first_half_ended_at"].tzinfo is not None
    assert fx["second_half_started_at"].tzinfo is not None
    assert fx["is_lineup_confirmed"] is True
    assert fx["has_preview"] is True


def test_parse_fixture_scheduled_without_lineup(raw_fixtures):
    fx = parse_fixture(raw_fixtures[1995471])
    assert fx["status"] == "scheduled"
    assert fx["home_score"] is None and fx["away_score"] is None
    assert fx["started_at"] is None
    assert fx["first_half_ended_at"] is None
    assert fx["second_half_started_at"] is None
    assert fx["is_lineup_confirmed"] is False
    assert fx["kickoff_time"] == datetime(2026, 11, 20, 20, 30, tzinfo=BERLIN)


def test_parse_fixture_summer_time_conversion(raw_fixtures):
    raw = dict(raw_fixtures[1995471], startTimeUtc="2026-08-28T18:30:00Z")
    kickoff = parse_fixture(raw)["kickoff_time"]
    assert kickoff.hour == 20 and kickoff.utcoffset().total_seconds() == 7200
    assert kickoff.tzinfo == BERLIN


def test_parse_fixture_cup_penalties():
    fx = parse_fixture(CUP_PEN_FIXTURE)
    assert fx["status"] == "finished"
    assert (fx["home_score"], fx["away_score"]) == (3, 3)
    assert (fx["et_home_score"], fx["et_away_score"]) == (3, 3)
    assert (fx["pen_home_score"], fx["pen_away_score"]) == (6, 5)
    assert fx["has_preview"] is False


def test_parse_fixture_naive_start_time_fallback(raw_fixtures):
    raw = dict(raw_fixtures[1995471])
    del raw["startTimeUtc"]
    assert parse_fixture(raw)["kickoff_time"] == datetime(2026, 11, 20, 20, 30, tzinfo=BERLIN)


def test_parse_fixture_missing_start_time(raw_fixtures):
    raw = dict(raw_fixtures[1995471], startTimeUtc=None, startTime=None)
    assert parse_fixture(raw)["kickoff_time"] is None


def test_parse_fixture_requires_ids(raw_fixtures):
    with pytest.raises(ValueError):
        parse_fixture({k: v for k, v in raw_fixtures[1995471].items() if k != "id"})
    with pytest.raises(ValueError):
        parse_fixture({k: v for k, v in raw_fixtures[1995471].items() if k != "homeTeamId"})


@pytest.mark.parametrize(
    ("status", "elapsed", "expected"),
    [
        (1, "", "scheduled"),
        (6, "FT", "finished"),
        (6, "", "finished"),
        (6, "AET", "finished"),
        (6, "PEN", "finished"),
        (3, "HT", "live"),
        (3, "34'", "live"),
        (3, "ET1", "live"),
        (3, "ET2", "live"),
        (2, "67", "live"),
        (4, "Post", "postponed"),
        (4, "Susp", "postponed"),
        (5, "Can", "cancelled"),
        (7, "Abd", "abandoned"),
        (None, None, "scheduled"),
        ("6", "ft", "finished"),
    ],
)
def test_map_fixture_status(status, elapsed, expected):
    assert map_fixture_status(status, elapsed) == expected


# ---------------------------------------------------------------------------
# Match Centre
# ---------------------------------------------------------------------------

def test_parse_match_centre_none_and_empty():
    assert parse_match_centre(None) is None
    assert parse_match_centre({}) is None


def test_parse_match_centre_invalid_structure():
    with pytest.raises(ValueError):
        parse_match_centre({"score": "1 : 0"})


def test_parse_match_centre_header(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    assert mc["venue_name"] == mc_own_goal["venueName"]
    assert isinstance(mc["attendance"], int)
    assert mc["referee"]["ws_official_id"] == mc_own_goal["referee"]["officialId"]
    assert mc["referee"]["name"] == mc_own_goal["referee"]["name"]
    assert (mc["ht_home_score"], mc["ht_away_score"]) == (1, 1)
    assert (mc["ft_home_score"], mc["ft_away_score"]) == (2, 3)
    assert mc["et_home_score"] is None and mc["pen_home_score"] is None
    assert mc["is_finished"] is True
    assert mc["has_lineups"] is True
    assert mc["home"]["ws_team_id"] == 1211
    assert mc["away"]["ws_team_id"] == 38


def test_parse_match_centre_is_finished_variants(mc_own_goal):
    raw = copy.deepcopy(mc_own_goal)
    raw["statusCode"] = 3
    raw["elapsed"] = "HT"
    assert parse_match_centre(raw)["is_finished"] is False
    raw["elapsed"] = "AET"
    assert parse_match_centre(raw)["is_finished"] is True


def test_parse_match_centre_has_lineups_false(mc_own_goal):
    raw = copy.deepcopy(mc_own_goal)
    for side in ("home", "away"):
        for player in raw[side]["players"]:
            player["isFirstEleven"] = False
    assert parse_match_centre(raw)["has_lineups"] is False


def test_parse_match_centre_extra_time_scores(mc_own_goal):
    raw = copy.deepcopy(mc_own_goal)
    raw["etScore"] = "3 : 3"
    raw["pkScore"] = "6 : 5"
    mc = parse_match_centre(raw)
    assert (mc["et_home_score"], mc["et_away_score"]) == (3, 3)
    assert (mc["pen_home_score"], mc["pen_away_score"]) == (6, 5)


def test_parse_match_centre_team_block_shape(mc_own_goal):
    home = parse_match_centre(mc_own_goal)["home"]
    assert set(home) >= {
        "ws_team_id", "name", "country_name", "manager_name", "average_age",
        "stats", "players", "formations", "incidents",
    }
    assert home["name"] == "Hoffenheim"
    assert isinstance(home["average_age"], float)
    assert home["manager_name"]
    assert all(isinstance(v, float) for v in home["stats"].values())


def test_parse_match_centre_team_stats_aggregation(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    home_raw = mc_own_goal["home"]["stats"]
    home = mc["home"]["stats"]
    assert home["passesTotal"] == float(sum(home_raw["passesTotal"].values()))
    assert home["touches"] == float(sum(home_raw["touches"].values()))
    for derived in DERIVED_STAT_KEYS:
        assert derived not in home
    assert "minutesWithStats" not in home
    assert "ratings" not in home


def test_parse_match_centre_possession_share(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    home_sum = sum(mc_own_goal["home"]["stats"]["possession"].values())
    away_sum = sum(mc_own_goal["away"]["stats"]["possession"].values())
    assert mc["home"]["stats"]["possession"] == round(100 * home_sum / (home_sum + away_sum), 1)
    assert mc["home"]["stats"]["possession"] + mc["away"]["stats"]["possession"] == pytest.approx(100, abs=0.11)


def test_parse_match_centre_possession_missing_opponent(mc_own_goal):
    raw = copy.deepcopy(mc_own_goal)
    del raw["away"]["stats"]["possession"]
    mc = parse_match_centre(raw)
    assert "possession" not in mc["home"]["stats"]
    assert "possession" not in mc["away"]["stats"]


def test_parse_match_centre_players(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    players = mc["home"]["players"]
    assert players
    starter = next(p for p in players if p["is_first_eleven"])
    assert set(starter) >= {
        "ws_player_id", "name", "shirt_no", "position", "height", "weight", "age",
        "is_first_eleven", "is_man_of_the_match", "rating",
        "subbed_in_minute", "subbed_out_minute", "stats",
    }
    assert isinstance(starter["rating"], float)
    assert "ratings" not in starter["stats"]
    for derived in DERIVED_STAT_KEYS:
        assert derived not in starter["stats"]
    raw_player = next(p for p in mc_own_goal["home"]["players"] if p["playerId"] == starter["ws_player_id"])
    last_minute = max(raw_player["stats"]["ratings"], key=int)
    assert starter["rating"] == raw_player["stats"]["ratings"][last_minute]
    # Auswechselspieler ohne isFirstEleven-Feld -> False
    bench = [p for p in players if not p["is_first_eleven"]]
    assert all(p["is_first_eleven"] is False for p in bench)


def test_parse_match_centre_substitution_minutes(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    raw_events = {
        (e["playerId"], e["type"]["displayName"]): e["minute"]
        for side in ("home", "away")
        for e in mc_own_goal[side]["incidentEvents"]
        if e["type"]["displayName"].startswith("Substitution")
    }
    assert raw_events, "Fixture enthält Wechsel-Events"
    checked = 0
    for side in ("home", "away"):
        for player in mc[side]["players"]:
            on = raw_events.get((player["ws_player_id"], "SubstitutionOn"))
            off = raw_events.get((player["ws_player_id"], "SubstitutionOff"))
            assert player["subbed_in_minute"] == on
            assert player["subbed_out_minute"] == off
            checked += on is not None or off is not None
    assert checked > 0


def test_parse_match_centre_incidents_goals_and_cards(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    home_inc = mc["home"]["incidents"]
    away_inc = mc["away"]["incidents"]
    assert {i["type"] for i in home_inc + away_inc} <= {"goal", "own_goal", "penalty_goal", "card"}

    goals_home = [i for i in home_inc if i["type"] == "goal"]
    assert len(goals_home) == 1
    assert goals_home[0]["ws_player_id"] == 433100
    assert goals_home[0]["related_ws_player_id"] == 428426
    assert goals_home[0]["ws_team_id"] == 1211
    assert goals_home[0]["minute"] == 52
    assert goals_home[0]["expanded_minute"] == 60
    assert goals_home[0]["period"] == "SecondHalf"
    assert goals_home[0]["card_type"] is None
    assert isinstance(goals_home[0]["ws_event_id"], int)

    cards = [i for i in home_inc if i["type"] == "card"]
    assert [c["card_type"] for c in cards] == ["yellow", "second_yellow", "yellow"]
    assert all(c["related_ws_player_id"] is None for c in cards)

    # keine Wechsel, keine Koordinaten
    for incident in home_inc + away_inc:
        assert "x" not in incident and "y" not in incident
    assert len(away_inc) == 4


def test_parse_match_centre_own_goal(mc_own_goal):
    mc = parse_match_centre(mc_own_goal)
    own = [i for i in mc["away"]["incidents"] if i["type"] == "own_goal"]
    assert len(own) == 1
    assert own[0]["ws_player_id"] == 364235
    assert own[0]["ws_team_id"] == 38          # Team des Eigentor-Schützen
    assert own[0]["credited_ws_team_id"] == 1211  # Tor zählt für den Gegner
    assert own[0]["minute"] == 50
    assert own[0]["minute_label"] == "45+5"


def test_parse_match_centre_penalty_goal(mc_penalty):
    mc = parse_match_centre(mc_penalty)
    penalties = [i for i in mc["home"]["incidents"] if i["type"] == "penalty_goal"]
    assert len(penalties) == 1
    assert penalties[0]["ws_player_id"] == 75217
    assert penalties[0]["credited_ws_team_id"] == penalties[0]["ws_team_id"]
    plain = [i for i in mc["home"]["incidents"] if i["type"] == "goal"]
    assert len(plain) == 2
    red_cards = [
        i for i in mc["home"]["incidents"] if i["type"] == "card" and i["card_type"] == "second_yellow"
    ]
    assert len(red_cards) == 1


def test_parse_match_centre_red_card(mc_own_goal):
    raw = copy.deepcopy(mc_own_goal)
    card = next(e for e in raw["home"]["incidentEvents"] if e["type"]["displayName"] == "Card")
    card["cardType"] = {"displayName": "Red", "value": 33}
    cards = [i for i in parse_match_centre(raw)["home"]["incidents"] if i["type"] == "card"]
    assert cards[0]["card_type"] == "red"


def test_parse_match_centre_formations(mc_own_goal):
    home = parse_match_centre(mc_own_goal)["home"]
    assert home["formations"]
    first = home["formations"][0]
    assert set(first) == {"name", "period", "start_minute", "end_minute", "captain_ws_player_id", "positions"}
    assert first["start_minute"] == 0
    assert len(first["positions"]) == 11
    assert [p["slot"] for p in first["positions"]] == list(range(1, 12))
    raw_first = mc_own_goal["home"]["formations"][0]
    # Slot 1 -> Spieler, dessen formationSlots-Eintrag 1 ist
    slot1_player = raw_first["playerIds"][raw_first["formationSlots"].index(1)]
    assert first["positions"][0]["ws_player_id"] == slot1_player
    assert first["positions"][0]["vertical"] == raw_first["formationPositions"][0]["vertical"]
    assert first["positions"][0]["horizontal"] == raw_first["formationPositions"][0]["horizontal"]
    assert all(isinstance(p["ws_player_id"], int) for p in first["positions"])


# ---------------------------------------------------------------------------
# Fehlende Spieler (Preview)
# ---------------------------------------------------------------------------

def test_parse_missing_players_html():
    result = parse_missing_players_html(_load_text("preview_missing_players.html"))
    assert len(result["home"]) == 5
    assert len(result["away"]) == 6
    first = result["home"][0]
    assert first == {
        "ws_player_id": 119501,
        "name": "Serge Gnabry",
        "reason": "injured",
        "status": "Out",
    }
    assert {p["reason"] for p in result["home"]} == {"injured", "unfit"}
    assert result["away"][0]["ws_player_id"] == 401632


def test_parse_missing_players_html_not_found_page_raises():
    with pytest.raises(ValueError):
        parse_missing_players_html(_load_text("preview_not_found.html"))


@pytest.mark.parametrize("html", ["", "   ", "<html><body>Blocked</body></html>"])
def test_parse_missing_players_html_invalid_raises(html):
    with pytest.raises(ValueError):
        parse_missing_players_html(html)


def test_parse_missing_players_html_valid_page_without_rows():
    # Synthetisch: gültige Preview, Tabellen ohne Zeilen bzw. ganz ohne Block
    empty_tables = (
        '<html><body><div id="match-header"></div><div id="missing-players">'
        '<div class="team-selector"></div>'
        '<div class="home"><table><tbody></tbody></table></div>'
        '<div class="away"><table><tbody></tbody></table></div></div></body></html>'
    )
    assert parse_missing_players_html(empty_tables) == {"home": [], "away": []}
    no_block = '<html><body><div id="match-header"></div></body></html>'
    assert parse_missing_players_html(no_block) == {"home": [], "away": []}


def test_parse_missing_players_html_status_without_reason():
    page = (
        '<html><body><div id="match-header"></div><div id="missing-players">'
        '<div class="team-selector"></div>'
        '<div class="home"><table><tbody><tr>'
        '<td class="pn"><a href="/players/1/show/a-b">A B</a></td>'
        '<td class="reason"></td><td class="confirmed">Doubtful</td></tr></tbody></table></div>'
        '<div class="away"><table><tbody></tbody></table></div></div></body></html>'
    )
    result = parse_missing_players_html(page)
    assert result["home"] == [{"ws_player_id": 1, "name": "A B", "reason": None, "status": "Doubtful"}]


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class FakeDriver:
    def __init__(self):
        self.quit_calls = 0

    def default_get(self, url):  # pragma: no cover - nur für Identitätsprüfung
        return None

    def get(self, url):  # pragma: no cover
        return None

    def quit(self):
        self.quit_calls += 1


class FakeWhoScored:
    """Ersatz für soccerdata.WhoScored: liefert vorbereitete Antworten und protokolliert Aufrufe."""

    def __init__(self, responses=None, error=None):
        self._driver = FakeDriver()
        self._selected_leagues = {"GER-Bundesliga": "Germany - Bundesliga"}
        self.responses = responses or {}
        self.error = error
        self.calls: list[dict] = []

    def get(self, url, filepath=None, max_age=None, no_cache=False, var=None):
        self.calls.append({"url": url, "filepath": filepath, "no_cache": no_cache, "var": var})
        if self.error is not None:
            raise self.error
        body = self.responses[(url, var)]
        if not isinstance(body, bytes):
            body = json.dumps(body).encode("utf-8") if not isinstance(body, str) else body.encode("utf-8")
        return io.BytesIO(body)


@pytest.fixture
def fake_factory(monkeypatch):
    """Ersetzt die lazy Factory; liefert (Liste erzeugter Fakes, Setter für Antworten)."""
    created: list[FakeWhoScored] = []
    state = {"responses": {}, "error": None}

    def factory(league_key, seasons):
        fake = FakeWhoScored(state["responses"], state["error"])
        created.append(fake)
        return fake

    monkeypatch.setattr(ws_module, "_create_whoscored", factory)
    yield created, state
    assert not WHOSCORED_BROWSER_LOCK.locked(), "Browser-Lock wurde nicht freigegeben"


BASE = "https://www.whoscored.com"
ALL_REGIONS = [
    {
        "id": 81,
        "name": "Germany",
        "type": 0,
        "tournaments": [
            {"id": 3, "name": "Bundesliga", "sortOrder": 170},
            {"id": 24, "name": "DFB-Pokal", "sortOrder": 25},
        ],
    },
    {"id": 250, "name": "Europe", "type": 1, "tournaments": [{"id": 12, "name": "Champions League", "sortOrder": 220}]},
]


def test_importing_datasources_does_not_import_soccerdata():
    repo_root = Path(__file__).resolve().parent.parent
    code = (
        "import sys; import app.services.datasources; "
        "import app.services.datasources.whoscored_parsers; "
        "assert 'soccerdata' not in sys.modules and 'selenium' not in sys.modules"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=repo_root, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_lock_blocks_second_client(fake_factory):
    with WhoScoredClient(lock_timeout=5) as first:
        assert first is not None
        with pytest.raises(BrowserBusyError):
            WhoScoredClient(lock_timeout=0).__enter__()
        with pytest.raises(BrowserBusyError):
            with WhoScoredClient(lock_timeout=0.05):
                pass
    # nach dem Schließen wieder frei
    with WhoScoredClient(lock_timeout=0):
        pass


def test_lock_released_after_exception(fake_factory):
    with pytest.raises(RuntimeError):
        with WhoScoredClient(lock_timeout=0):
            raise RuntimeError("boom")
    assert not WHOSCORED_BROWSER_LOCK.locked()


def test_default_lock_timeout_from_settings(monkeypatch):
    monkeypatch.setattr(ws_module.settings, "whoscored_lock_timeout_seconds", 42)
    assert WhoScoredClient().lock_timeout == 42.0
    assert WhoScoredClient(lock_timeout=0).lock_timeout == 0.0


def test_browser_starts_lazily_and_only_once(fake_factory):
    created, state = fake_factory
    state["responses"] = {
        (f"{BASE}/Matches/1/Live", ws_module.MATCH_CENTRE_VAR): None,
        (f"{BASE}/Matches/2/Live", ws_module.MATCH_CENTRE_VAR): None,
    }
    with WhoScoredClient(lock_timeout=0) as client:
        assert created == [] and client.pages_loaded == 0
        client.fetch_match_centre(1)
        client.fetch_match_centre(2)
        assert len(created) == 1
        assert client.pages_loaded == 2
    assert created[0]._driver.quit_calls == 1


def test_close_without_browser_and_idempotent(fake_factory):
    created, _ = fake_factory
    client = WhoScoredClient(lock_timeout=0)
    client.__enter__()
    client.close()
    client.close()
    assert created == []


def test_driver_quit_on_exit_even_after_error(fake_factory):
    created, state = fake_factory
    state["error"] = ConnectionError("Could not download")
    with pytest.raises(WhoScoredError):
        with WhoScoredClient(lock_timeout=0) as client:
            client.fetch_match_centre(1)
    assert created[0]._driver.quit_calls == 1


def test_browser_start_failure_wrapped(monkeypatch):
    def factory(league_key, seasons):
        raise RuntimeError("chrome fehlt")

    monkeypatch.setattr(ws_module, "_create_whoscored", factory)
    with pytest.raises(WhoScoredError, match="chrome fehlt"):
        with WhoScoredClient(lock_timeout=0) as client:
            client.fetch_match_centre(1)
    assert not WHOSCORED_BROWSER_LOCK.locked()


def test_driver_missing_raises(monkeypatch):
    class NoDriver:
        pass

    monkeypatch.setattr(ws_module, "_create_whoscored", lambda *a: NoDriver())
    with pytest.raises(WhoScoredError):
        with WhoScoredClient(lock_timeout=0) as client:
            client.fetch_match_centre(1)


def test_get_uses_no_cache_and_plain_driver_get(fake_factory):
    created, state = fake_factory
    state["responses"] = {(f"{BASE}/Matches/9/Live", ws_module.MATCH_CENTRE_VAR): None}
    with WhoScoredClient(lock_timeout=0) as client:
        client.fetch_match_centre(9)
        ws = created[0]
        assert ws.calls == [
            {
                "url": f"{BASE}/Matches/9/Live",
                "filepath": None,
                "no_cache": True,
                "var": "require.config.params['args'].matchCentreData",
            }
        ]
        assert ws._driver.get == ws._driver.default_get


def test_fetch_match_centre_parses(fake_factory, mc_own_goal):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/Matches/1995456/Live", ws_module.MATCH_CENTRE_VAR): mc_own_goal}
    with WhoScoredClient(lock_timeout=0) as client:
        mc = client.fetch_match_centre(1995456)
    assert mc["home"]["ws_team_id"] == 1211
    assert mc["is_finished"] is True


def test_fetch_match_centre_unavailable_returns_none(fake_factory):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/Matches/5/Live", ws_module.MATCH_CENTRE_VAR): None}
    with WhoScoredClient(lock_timeout=0) as client:
        assert client.fetch_match_centre(5) is None


def test_fetch_missing_players_url_and_result(fake_factory):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/Matches/7/Preview", None): _load_text("preview_missing_players.html")}
    with WhoScoredClient(lock_timeout=0) as client:
        result = client.fetch_missing_players(7)
    assert len(result["home"]) == 5


def test_fetch_missing_players_invalid_page_raises_whoscored_error(fake_factory):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/Matches/8/Preview", None): _load_text("preview_not_found.html")}
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_missing_players(8)


def test_fetch_fixtures_month_url_and_parsing(fake_factory):
    _, state = fake_factory
    url = f"{BASE}/tournaments/25666/data/?d=202611"
    state["responses"] = {(url, None): _load_json("fixtures_month.json")}
    with WhoScoredClient(lock_timeout=0) as client:
        fixtures = client.fetch_fixtures_month(25666, 2026, 11)
    assert [f["ws_match_id"] for f in fixtures] == [1995458, 1995471, 1995474]
    assert {f["status"] for f in fixtures} == {"finished", "scheduled"}


def test_fetch_fixtures_month_pads_month(fake_factory):
    created, state = fake_factory
    state["responses"] = {(f"{BASE}/tournaments/25666/data/?d=202608", None): {"tournaments": []}}
    with WhoScoredClient(lock_timeout=0) as client:
        assert client.fetch_fixtures_month(25666, 2026, 8) == []
    assert created[0].calls[0]["url"].endswith("?d=202608")


def test_fetch_fixtures_month_skips_broken_matches(fake_factory):
    _, state = fake_factory
    good = _load_json("fixtures_month.json")["tournaments"][0]["matches"][0]
    broken = {"id": 1, "homeTeamName": "X"}
    state["responses"] = {
        (f"{BASE}/tournaments/1/data/?d=202609", None): {"tournaments": [{"matches": [broken, good, good]}]}
    }
    with WhoScoredClient(lock_timeout=0) as client:
        fixtures = client.fetch_fixtures_month(1, 2026, 9)
    assert [f["ws_match_id"] for f in fixtures] == [good["id"]]


def test_fetch_fixtures_month_unexpected_format(fake_factory):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/tournaments/1/data/?d=202609", None): {"oops": 1}}
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_fixtures_month(1, 2026, 9)


def test_fetch_fixtures_month_non_json_response(fake_factory):
    _, state = fake_factory
    state["responses"] = {(f"{BASE}/tournaments/1/data/?d=202609", None): "<html>blocked</html>"}
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_fixtures_month(1, 2026, 9)


def test_fetch_calendar_months(fake_factory):
    _, state = fake_factory
    url = f"{BASE}/Regions/81/Tournaments/3/Seasons/11217/Stages/25666"
    calendar = {
        "mask": {
            "2026": {"10": {"1": 1, "20": 1}, "7": {"28": 1}, "11": {"4": 1}},
            "2027": {"0": {"8": 1}, "4": {"15": 1}},
        },
        "stageId": 25666,
    }
    state["responses"] = {(url, "wsCalendar"): calendar}
    with WhoScoredClient(lock_timeout=0) as client:
        months = client.fetch_calendar_months(81, 3, 11217, 25666)
    # Monate sind 0-basiert im Mask -> real 1-12
    assert months == [(2026, 8), (2026, 11), (2026, 12), (2027, 1), (2027, 5)]


def test_fetch_calendar_months_missing_calendar_raises(fake_factory):
    _, state = fake_factory
    url = f"{BASE}/Regions/81/Tournaments/3/Seasons/1/Stages/2"
    state["responses"] = {(url, "wsCalendar"): None}
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_calendar_months(81, 3, 1, 2)


def test_fetch_available_competitions(fake_factory):
    _, state = fake_factory
    state["responses"] = {(BASE, "allRegions"): ALL_REGIONS}
    with WhoScoredClient(lock_timeout=0) as client:
        comps = client.fetch_available_competitions()
    assert len(comps) == 3
    assert comps[0] == {
        "ws_region_id": 81,
        "region": "Germany",
        "ws_tournament_id": 3,
        "tournament": "Bundesliga",
        "region_type": 0,
        "sort_order": 170,
    }
    assert {c["tournament"] for c in comps} == {"Bundesliga", "DFB-Pokal", "Champions League"}


def test_fetch_available_competitions_empty_raises(fake_factory):
    _, state = fake_factory
    state["responses"] = {(BASE, "allRegions"): None}
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_available_competitions()


TOURNAMENT_PAGE = (
    '<html><body><select id="seasons" name="seasons">'
    '<option selected="selected" value="/Regions/81/Tournaments/3/Seasons/11217/germany-bundesliga">2026/2027</option>'
    '<option value="/Regions/81/Tournaments/3/Seasons/10720/germany-bundesliga">2025/2026</option>'
    "</select></body></html>"
)
SEASON_PAGE_SIMPLE = (
    "<html><body><a href=\"/regions/81/tournaments/3/seasons/11217/stages/25666/fixtures/germany-bundesliga-2026-2027\">"
    "Fixtures</a></body></html>"
)
SEASON_PAGE_STAGES = (
    "<html><body><a href=\"/regions/250/tournaments/12/seasons/11295/stages/25800/fixtures/x\">Fixtures</a>"
    '<select id="stages" name="stages">'
    '<option value="/Regions/250/Tournaments/12/Seasons/11295/Stages/25800/Show/x">League Phase</option>'
    '<option value="/Regions/250/Tournaments/12/Seasons/11295/Stages/25801/Show/x">Knockout</option>'
    "</select></body></html>"
)


def test_fetch_season_metadata_via_league_key(fake_factory):
    created, state = fake_factory
    state["responses"] = {
        (BASE, "allRegions"): ALL_REGIONS,
        (f"{BASE}/Regions/81/Tournaments/3", None): TOURNAMENT_PAGE,
        (f"{BASE}/Regions/81/Tournaments/3/Seasons/11217", None): SEASON_PAGE_SIMPLE,
    }
    with WhoScoredClient("GER-Bundesliga", lock_timeout=0) as client:
        meta = client.fetch_season_metadata("2627")
        assert client.pages_loaded == 3
    assert meta == {
        "region": {"ws_region_id": 81, "name": "Germany"},
        "competition": {"ws_tournament_id": 3, "name": "Bundesliga"},
        "season": {"ws_season_id": 11217, "code": "2627"},
        "stages": [{"ws_stage_id": 25666, "name": None, "is_default": True}],
    }
    assert all(call["filepath"] is None and call["no_cache"] for call in created[0].calls)


def test_fetch_season_metadata_with_ids_and_stages(fake_factory):
    _, state = fake_factory
    state["responses"] = {
        (BASE, "allRegions"): ALL_REGIONS,
        (f"{BASE}/Regions/250/Tournaments/12", None): TOURNAMENT_PAGE.replace("/Regions/81/Tournaments/3/", "/Regions/250/Tournaments/12/").replace("11217", "11295"),
        (f"{BASE}/Regions/250/Tournaments/12/Seasons/11295", None): SEASON_PAGE_STAGES,
    }
    with WhoScoredClient(lock_timeout=0) as client:
        meta = client.fetch_season_metadata("2026/2027", ws_region_id=250, ws_tournament_id=12)
    assert meta["competition"] == {"ws_tournament_id": 12, "name": "Champions League"}
    assert meta["stages"] == [
        {"ws_stage_id": 25800, "name": "League Phase", "is_default": True},
        {"ws_stage_id": 25801, "name": "Knockout", "is_default": False},
    ]


def test_fetch_season_metadata_season_not_found(fake_factory):
    _, state = fake_factory
    state["responses"] = {
        (BASE, "allRegions"): ALL_REGIONS,
        (f"{BASE}/Regions/81/Tournaments/3", None): TOURNAMENT_PAGE,
    }
    with WhoScoredClient("GER-Bundesliga", lock_timeout=0) as client:
        with pytest.raises(WhoScoredError, match="1920"):
            client.fetch_season_metadata("1920")


def test_fetch_season_metadata_unknown_league_key(fake_factory):
    _, state = fake_factory
    state["responses"] = {(BASE, "allRegions"): ALL_REGIONS}
    with WhoScoredClient("XXX-Unknown", lock_timeout=0) as client:
        with pytest.raises(WhoScoredError):
            client.fetch_season_metadata("2627")


@pytest.mark.parametrize(
    ("value", "expected"),
    [("2026/2027", "2627"), ("2026-27", "2627"), ("2627", "2627"), ("2022", "2022"), (" 2025/2026 ", "2526")],
)
def test_normalize_season_code(value, expected):
    assert normalize_season_code(value) == expected


def test_normalize_season_code_invalid():
    with pytest.raises(WhoScoredError):
        normalize_season_code("abc")


def test_wrapped_connection_error_message(fake_factory):
    _, state = fake_factory
    state["error"] = ConnectionError("Could not download")
    with WhoScoredClient(lock_timeout=0) as client:
        with pytest.raises(WhoScoredError, match="Matches/3/Preview"):
            client.fetch_missing_players(3)
