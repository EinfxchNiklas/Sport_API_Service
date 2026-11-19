"""Tests der WhoScored-Schreibseite (``football_service``) mit SQLite und einem FakeClient.

Die Daten stammen aus den echten (getrimmten) Fixtures unter ``tests/fixtures/whoscored``.
"""

from __future__ import annotations

import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session

from app.models import (
    Appearance,
    Base,
    Competition,
    Country,
    Formation,
    FormationPosition,
    Match,
    MatchIncident,
    MatchSyncState,
    MatchTeam,
    MissingPlayer,
    Player,
    PlayerMatchStat,
    Region,
    Season,
    Stage,
    StatType,
    Team,
    TeamMatchStat,
    Venue,
)
from app.services import football_service as fs
from app.services.datasources.whoscored import WhoScoredError
from app.services.datasources.whoscored_parsers import (
    parse_fixture,
    parse_match_centre,
    parse_missing_players_html,
)
from app.services.football_competitions import (
    COMPETITIONS,
    current_season_code,
    enabled_competitions,
    get_competition_config,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "whoscored"
BERLIN = ZoneInfo("Europe/Berlin")

STAGE_WS_ID = 25666
SEASON_WS_ID = 9999
LEAGUE = "GER-Bundesliga"

# Match-IDs der Tests (Teams der Match-Centre-Fixtures: Hoffenheim 1211 vs Leverkusen 36 / Hamburg 38)
PEN_MATCH = 1900001
OWN_GOAL_MATCH = 1900002


def _load_json(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _raw_month() -> dict[int, dict]:
    data = _load_json("fixtures_month.json")
    return {m["id"]: m for t in data["tournaments"] for m in t["matches"]}


def make_fixture(base_id: int, **overrides) -> dict:
    """Geparstes Fixture auf Basis eines echten Roh-Spiels (Felder überschreibbar)."""
    raw = dict(_raw_month()[base_id])
    raw.update(overrides)
    return parse_fixture(raw)


def centre_penalty() -> dict:
    return parse_match_centre(_load_json("match_centre_penalty.json"))


def centre_own_goal() -> dict:
    return parse_match_centre(_load_json("match_centre_own_goal.json"))


def finished_fixture(ws_match_id: int, away_id: int, away_name: str, day: int) -> dict:
    return make_fixture(
        1995458,
        id=ws_match_id,
        homeTeamId=1211,
        homeTeamName="Hoffenheim",
        awayTeamId=away_id,
        awayTeamName=away_name,
        startTimeUtc=f"2026-11-{day:02d}T14:30:00Z",
        startedAtUtc=f"2026-11-{day:02d}T14:30:08Z",
        firstHalfEndedAtUtc=f"2026-11-{day:02d}T15:17:08Z",
        secondHalfStartedAtUtc=f"2026-11-{day:02d}T15:33:48Z",
    )


class FakeClient:
    """Gleiche Methodennamen wie ``WhoScoredClient``; zählt Aufrufe und Seitenladungen."""

    def __init__(self, fixtures=None, centres=None, previews=None, stage_ws_ids=(STAGE_WS_ID,)):
        self.pages_loaded = 0
        self.calls: list[tuple] = []
        self.fixtures: dict[tuple[int, int, int], list[dict]] = fixtures or {}
        self.centres: dict = centres or {}
        self.previews: dict = previews or {}
        self.stage_ws_ids = list(stage_ws_ids)

    def _page(self, *call, pages: int = 1):
        self.pages_loaded += pages
        self.calls.append(call)

    def count(self, name: str) -> int:
        return sum(1 for call in self.calls if call[0] == name)

    def fetch_season_metadata(self, season_code, ws_region_id=None, ws_tournament_id=None):
        self._page("season_metadata", season_code, ws_region_id, ws_tournament_id, pages=3)
        return {
            "region": {"ws_region_id": ws_region_id, "name": "Germany"},
            "competition": {"ws_tournament_id": ws_tournament_id, "name": "Bundesliga"},
            "season": {"ws_season_id": SEASON_WS_ID, "code": season_code},
            "stages": [
                {"ws_stage_id": ws_id, "name": None, "is_default": index == 0}
                for index, ws_id in enumerate(self.stage_ws_ids)
            ],
        }

    def fetch_calendar_months(self, ws_region_id, ws_tournament_id, ws_season_id, ws_stage_id):
        self._page("calendar", ws_stage_id)
        return sorted({(y, m) for (stage, y, m) in self.fixtures if stage == ws_stage_id})

    def fetch_fixtures_month(self, ws_stage_id, year, month):
        self._page("fixtures_month", ws_stage_id, year, month)
        return copy.deepcopy(self.fixtures.get((ws_stage_id, year, month), []))

    def fetch_match_centre(self, ws_match_id):
        self._page("match_centre", ws_match_id)
        value = self.centres.get(ws_match_id)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)

    def fetch_missing_players(self, ws_match_id):
        self._page("missing_players", ws_match_id)
        value = self.previews.get(ws_match_id)
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(params=[True, False], ids=["autoflush", "noautoflush"])
def db(engine, request):
    # SessionLocal der App läuft mit autoflush=False -> beide Varianten testen
    with Session(engine, autoflush=request.param) as session:
        yield session


@pytest.fixture
def statements(engine):
    """Liste der ausgeführten SQL-Statements (nur Anwendungs-Statements, keine PRAGMAs)."""
    collected: list[str] = []

    @event.listens_for(engine, "before_cursor_execute")
    def _collect(conn, cursor, statement, parameters, context, executemany):
        if not statement.startswith("PRAGMA"):
            collected.append(statement)

    return collected


def seed_season(db, client: FakeClient | None = None):
    client = client or FakeClient()
    return fs.ensure_season(db, client, LEAGUE, "2627")


def seed_matches(db, fixtures: list[dict]) -> tuple[Season, FakeClient]:
    """Legt Saison + Spiele über ``sync_fixtures`` an."""
    client = FakeClient(fixtures={(STAGE_WS_ID, 2026, 11): fixtures})
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    fs.sync_fixtures(db, client, season)
    return season, client


def get_match(db, ws_match_id: int) -> Match:
    return db.scalars(select(Match).where(Match.ws_match_id == ws_match_id)).one()


def count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

def test_current_season_code_edge_cases():
    assert current_season_code(datetime(2026, 11, 19, tzinfo=BERLIN)) == "2627"
    assert current_season_code(datetime(2027, 1, 15, tzinfo=BERLIN)) == "2627"
    assert current_season_code(datetime(2026, 7, 1, tzinfo=BERLIN)) == "2627"
    assert current_season_code(datetime(2026, 6, 30, 23, 59, tzinfo=BERLIN)) == "2526"
    assert current_season_code(datetime(2099, 12, 31)) == "9900"
    assert current_season_code(datetime(1999, 9, 1)) == "9900"
    assert current_season_code(datetime(2026, 7, 15), start_month=8) == "2526"
    assert current_season_code(datetime(2026, 8, 1), start_month=8) == "2627"


def test_current_season_code_defaults_to_now():
    assert len(current_season_code()) == 4


def test_get_competition_config_ok_and_error():
    cfg = get_competition_config("GER-DFB-Pokal")
    assert (cfg.ws_region_id, cfg.ws_tournament_id, cfg.format) == (81, 24, "cup")
    with pytest.raises(ValueError) as exc:
        get_competition_config("XXX-Nope")
    for key in COMPETITIONS:
        assert key in str(exc.value)


def test_registry_has_all_ten_competitions():
    assert len(COMPETITIONS) == 10
    assert COMPETITIONS["INT-Conference League"].ws_tournament_id == 715
    assert len({c.slug for c in COMPETITIONS.values()}) == 10


def test_enabled_competitions_skips_unknown(monkeypatch, caplog):
    from app.services import football_competitions as fc

    monkeypatch.setattr(fc.settings, "whoscored_leagues", "GER-Bundesliga, XXX-Unknown ,INT-Champions League")
    with caplog.at_level(logging.WARNING):
        result = enabled_competitions()
    assert [c.league_key for c in result] == ["GER-Bundesliga", "INT-Champions League"]
    assert "XXX-Unknown" in caplog.text


# ---------------------------------------------------------------------------
# ensure_season
# ---------------------------------------------------------------------------

def test_ensure_season_creates_with_explicit_ids(db):
    client = FakeClient(stage_ws_ids=(STAGE_WS_ID, 25667))
    season = fs.ensure_season(db, client, "GER-DFB-Pokal", "2627")
    assert client.calls[0] == ("season_metadata", "2627", 81, 24)
    assert client.pages_loaded == 3
    competition = db.get(Competition, season.competition_id)
    assert (competition.league_key, competition.slug, competition.format) == ("GER-DFB-Pokal", "dfb-pokal", "cup")
    assert db.get(Region, competition.region_id).name == "Germany"
    stages = db.scalars(select(Stage).where(Stage.season_id == season.id).order_by(Stage.id)).all()
    assert [(s.ws_stage_id, s.is_default) for s in stages] == [(STAGE_WS_ID, True), (25667, False)]


def test_ensure_season_existing_makes_no_page_load(db):
    client = FakeClient()
    first = fs.ensure_season(db, client, LEAGUE, "2627")
    pages = client.pages_loaded
    second = fs.ensure_season(db, client, LEAGUE, "2026/2027")
    assert second.id == first.id
    assert client.pages_loaded == pages


def test_ensure_season_refresh_updates_without_duplicates(db):
    client = FakeClient()
    fs.ensure_season(db, client, LEAGUE, "2627")
    client.stage_ws_ids = [STAGE_WS_ID, 25999]
    season = fs.ensure_season(db, client, LEAGUE, "2627", refresh=True)
    assert client.count("season_metadata") == 2
    assert count(db, Season) == 1
    assert count(db, Competition) == 1
    assert count(db, Region) == 1
    assert count(db, Stage) == 2
    assert season.code == "2627"


def test_ensure_season_unknown_league_raises(db):
    with pytest.raises(ValueError):
        fs.ensure_season(db, FakeClient(), "XXX-Nope", "2627")


# ---------------------------------------------------------------------------
# sync_fixtures
# ---------------------------------------------------------------------------

def _month_fixtures() -> list[dict]:
    return [parse_fixture(m) for m in _raw_month().values()]


def test_sync_fixtures_creates_then_is_idempotent(db):
    client = FakeClient(fixtures={(STAGE_WS_ID, 2026, 11): _month_fixtures()})
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    pages_before = client.pages_loaded

    first = fs.sync_fixtures(db, client, season)
    assert (first["created"], first["updated"], first["unchanged"]) == (3, 0, 0)
    assert first["pages"] == client.pages_loaded - pages_before == 2  # Kalender + 1 Monat
    assert first["newly_finished"] == []
    assert count(db, Match) == 3
    assert count(db, Team) == 5
    assert count(db, MatchSyncState) == 3
    assert db.scalar(select(Country.code).where(Country.name == "Germany")) == "de"

    before = {m.ws_match_id: m.last_updated for m in db.scalars(select(Match))}
    second = fs.sync_fixtures(db, client, season)
    assert (second["created"], second["updated"], second["unchanged"]) == (0, 0, 3)
    assert count(db, Match) == 3 and count(db, Team) == 5 and count(db, MatchSyncState) == 3
    db.expire_all()
    after = {m.ws_match_id: m.last_updated for m in db.scalars(select(Match))}
    assert after == before  # keine echten Änderungen -> kein UPDATE


def test_sync_fixtures_fills_match_fields(db):
    seed_matches(db, _month_fixtures())
    match = get_match(db, 1995458)
    assert match.status == "finished"
    assert (match.home_score, match.away_score) == (1, 1)
    assert fs._same_dt(match.kickoff_time, datetime(2026, 11, 1, 15, 30, tzinfo=BERLIN))
    assert fs._same_dt(match.started_at, datetime(2026, 11, 1, 15, 30, 8, tzinfo=BERLIN))
    assert match.home_team.name == "Union Berlin"
    assert match.home_team.country.name == "Germany"
    state = db.get(MatchSyncState, match.id)
    assert state.fixture_synced_at is not None


def test_sync_fixtures_newly_finished_detection(db):
    fixtures = _month_fixtures()
    season, client = seed_matches(db, fixtures)
    scheduled = get_match(db, 1995471)
    scheduled_id = scheduled.id
    assert scheduled.status == "scheduled"

    updated = [f for f in fixtures]
    updated[1] = dict(
        fixtures[1],
        status="finished",
        home_score=2,
        away_score=0,
        started_at=datetime(2026, 11, 20, 20, 30, 5, tzinfo=BERLIN),
    )
    client.fixtures[(STAGE_WS_ID, 2026, 11)] = updated
    result = fs.sync_fixtures(db, client, season)
    assert result["newly_finished"] == [scheduled_id]
    assert (result["created"], result["updated"], result["unchanged"]) == (0, 1, 2)

    # erneuter Lauf: nicht mehr "neu beendet"
    again = fs.sync_fixtures(db, client, season)
    assert again["newly_finished"] == []
    assert again["unchanged"] == 3


def test_sync_fixtures_never_overwrites_with_none_but_updates_status(db):
    fixtures = _month_fixtures()
    season, client = seed_matches(db, fixtures)
    stripped = dict(
        fixtures[0],
        status="live",
        home_score=None,
        away_score=None,
        started_at=None,
        first_half_ended_at=None,
        second_half_started_at=None,
        kickoff_time=None,
        et_home_score=None,
    )
    client.fixtures[(STAGE_WS_ID, 2026, 11)] = [stripped] + fixtures[1:]
    result = fs.sync_fixtures(db, client, season)
    assert result["updated"] == 1
    db.expire_all()
    match = get_match(db, 1995458)
    assert match.status == "live"
    assert (match.home_score, match.away_score) == (1, 1)
    assert match.started_at is not None and match.first_half_ended_at is not None
    assert fs._same_dt(match.kickoff_time, datetime(2026, 11, 1, 15, 30, tzinfo=BERLIN))


def test_sync_fixtures_kickoff_change_is_applied(db):
    fixtures = _month_fixtures()
    season, client = seed_matches(db, fixtures)
    moved = dict(fixtures[1], kickoff_time=datetime(2026, 11, 21, 18, 30, tzinfo=BERLIN))
    client.fixtures[(STAGE_WS_ID, 2026, 11)] = [fixtures[0], moved, fixtures[2]]
    result = fs.sync_fixtures(db, client, season)
    assert result["updated"] == 1
    db.expire_all()
    assert fs._same_dt(get_match(db, 1995471).kickoff_time, datetime(2026, 11, 21, 18, 30, tzinfo=BERLIN))


def test_sync_fixtures_explicit_months_skip_calendar(db):
    fixtures = _month_fixtures()
    client = FakeClient(fixtures={(STAGE_WS_ID, 2026, 11): fixtures, (STAGE_WS_ID, 2026, 12): []})
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    result = fs.sync_fixtures(db, client, season, months=[(2026, 11)])
    assert result["pages"] == 1
    assert client.count("calendar") == 0
    assert result["created"] == 3


def test_sync_fixtures_multiple_stages_and_stage_fallback(db):
    # Spiel mit unbekannter stageId landet in der gerade synchronisierten Stage
    unknown_stage = make_fixture(1995471, stageId=77777)
    known_stage = make_fixture(1995474, stageId=25667)
    client = FakeClient(
        fixtures={(STAGE_WS_ID, 2026, 11): [unknown_stage], (25667, 2026, 12): [known_stage]},
        stage_ws_ids=(STAGE_WS_ID, 25667),
    )
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    result = fs.sync_fixtures(db, client, season)
    assert result["created"] == 2
    stage_by_match = {
        m.ws_match_id: db.get(Stage, m.stage_id).ws_stage_id for m in db.scalars(select(Match))
    }
    assert stage_by_match == {1995471: STAGE_WS_ID, 1995474: 25667}


def test_sync_fixtures_country_code_conflict_does_not_crash(db):
    fixtures = [
        make_fixture(1995471, homeTeamCountryName="Germany", awayTeamCountryName="Austria", awayTeamCountryCode="de"),
    ]
    seed_matches(db, fixtures)
    assert db.scalar(select(Country.code).where(Country.name == "Austria")) is None
    assert db.scalar(select(Country.code).where(Country.name == "Germany")) == "de"


# ---------------------------------------------------------------------------
# sync_match_details
# ---------------------------------------------------------------------------

def _seed_pen_match(db, status_fixture: dict | None = None):
    fixture = status_fixture or finished_fixture(PEN_MATCH, 36, "Leverkusen", 8)
    season, client = seed_matches(db, [fixture])
    return get_match(db, fixture["ws_match_id"]), client


def _expected_counts(centre: dict) -> dict:
    blocks = (centre["home"], centre["away"])
    return {
        "appearances": sum(len(b["players"]) for b in blocks),
        "player_stats": sum(len(p["stats"]) for b in blocks for p in b["players"]),
        "team_stats": sum(len(b["stats"]) for b in blocks),
        "incidents": sum(len(b["incidents"]) for b in blocks),
        "formations": sum(len(b["formations"]) for b in blocks),
    }


def test_sync_match_details_full_insert(db):
    match, _ = _seed_pen_match(db)
    centre = centre_penalty()
    client = FakeClient(centres={PEN_MATCH: centre})
    expected = _expected_counts(centre)

    result = fs.sync_match_details(db, client, match, final=True)
    assert result["status"] == "ok"
    for key, value in expected.items():
        assert result[key] == value
    assert expected["player_stats"] > 100 and expected["incidents"] >= 5

    assert count(db, Appearance) == expected["appearances"]
    assert count(db, PlayerMatchStat) == expected["player_stats"]
    assert count(db, TeamMatchStat) == expected["team_stats"]
    assert count(db, MatchIncident) == expected["incidents"]
    assert count(db, Formation) == expected["formations"]
    assert count(db, FormationPosition) == sum(
        len(f["positions"]) for b in (centre["home"], centre["away"]) for f in b["formations"]
    )
    assert count(db, MatchTeam) == 2

    db.expire_all()
    match = get_match(db, PEN_MATCH)
    assert match.venue.name == "SNP Arena"
    assert match.referee.name == "Daniel Siebert"
    assert match.attendance == 27378
    assert (match.ht_home_score, match.ht_away_score) == (0, 0)
    assert (match.home_score, match.away_score) == (1, 1)  # Fixture-Stand bleibt (FT nur Fallback)
    assert match.status == "finished"
    assert {mt.manager.name for mt in db.scalars(select(MatchTeam))} == {"Christian Ilzer", "Carles Martínez"}

    state = db.get(MatchSyncState, match.id)
    assert state.details_synced_at is not None and state.details_final_at is not None
    assert state.lineups_confirmed_at is not None
    assert state.attempts == 1 and state.last_error is None

    # Ereignis-Verweise zeigen auf vorhandene Spieler (Platzhalter für unbekannte), None nur wenn die Quelle keinen hat
    without_player = sum(1 for b in (centre["home"], centre["away"]) for i in b["incidents"] if i["ws_player_id"] is None)
    assert (
        db.scalar(select(func.count()).select_from(MatchIncident).where(MatchIncident.player_id.is_(None)))
        == without_player
    )
    assert db.scalar(select(StatType.id).where(StatType.key == "passesTotal")) is not None
    assert "passSuccess" not in {k for (k,) in db.execute(select(StatType.key))}


def test_sync_match_details_ft_score_fills_only_when_missing(db):
    fixture = make_fixture(
        1995471, id=PEN_MATCH, homeTeamId=1211, homeTeamName="Hoffenheim", awayTeamId=36, awayTeamName="Leverkusen"
    )
    seed_matches(db, [fixture])
    match = get_match(db, PEN_MATCH)
    assert match.home_score is None
    client = FakeClient(centres={PEN_MATCH: centre_penalty()})
    assert fs.sync_match_details(db, client, match)["status"] == "ok"
    db.expire_all()
    match = get_match(db, PEN_MATCH)
    assert (match.home_score, match.away_score) == (3, 0)
    assert match.status == "finished"  # Centre sagt: beendet
    state = db.get(MatchSyncState, match.id)
    assert state.details_final_at is None  # nicht final angefordert


def test_sync_match_details_own_goal_belongs_to_scorers_team(db):
    fixture = finished_fixture(OWN_GOAL_MATCH, 38, "Hamburg", 9)
    seed_matches(db, [fixture])
    match = get_match(db, OWN_GOAL_MATCH)
    client = FakeClient(centres={OWN_GOAL_MATCH: centre_own_goal()})
    assert fs.sync_match_details(db, client, match)["status"] == "ok"
    own_goal = db.scalars(select(MatchIncident).where(MatchIncident.type == "own_goal")).one()
    scorer_team = db.scalars(select(Team).where(Team.ws_team_id == 38)).one()
    assert own_goal.team_id == scorer_team.id
    assert own_goal.ws_event_id == 2979263093  # > 2^31
    assert own_goal.minute == 50


def test_sync_match_details_resync_updates_without_duplicates(db):
    match, _ = _seed_pen_match(db)
    centre = centre_penalty()
    client = FakeClient(centres={PEN_MATCH: centre})
    fs.sync_match_details(db, client, match)
    totals = {m: count(db, m) for m in (Appearance, PlayerMatchStat, TeamMatchStat, MatchIncident, Formation,
                                         FormationPosition, Player, StatType, MatchTeam, Venue)}

    # Rating und Statistikwert ändern
    changed = copy.deepcopy(centre)
    player = changed["home"]["players"][0]
    old_rating = player["rating"]
    stat_key = next(iter(player["stats"]))
    player["rating"] = 9.9
    player["stats"][stat_key] = player["stats"][stat_key] + 5
    changed["home"]["stats"]["possession"] = 61.5
    client.centres[PEN_MATCH] = changed
    result = fs.sync_match_details(db, client, db.get(Match, match.id))
    assert result["status"] == "ok"

    assert totals == {m: count(db, m) for m in totals}
    appearance = db.scalars(
        select(Appearance).join(Player, Player.id == Appearance.player_id).where(
            Player.ws_player_id == player["ws_player_id"]
        )
    ).one()
    assert appearance.rating == 9.9 and appearance.rating != old_rating
    stat_value = db.scalar(
        select(PlayerMatchStat.value)
        .join(StatType, StatType.id == PlayerMatchStat.stat_type_id)
        .where(PlayerMatchStat.appearance_id == appearance.id, StatType.key == stat_key)
    )
    assert stat_value == pytest.approx(player["stats"][stat_key])
    possession = db.scalar(
        select(TeamMatchStat.value)
        .join(StatType, StatType.id == TeamMatchStat.stat_type_id)
        .join(Team, Team.id == TeamMatchStat.team_id)
        .where(StatType.key == "possession", Team.ws_team_id == 1211)
    )
    assert possession == 61.5
    state = db.get(MatchSyncState, match.id)
    assert state.attempts == 2


def test_sync_match_details_adds_new_rows_on_resync(db):
    match, _ = _seed_pen_match(db)
    centre = centre_penalty()
    client = FakeClient(centres={PEN_MATCH: centre})
    fs.sync_match_details(db, client, match)
    incidents = count(db, MatchIncident)

    extended = copy.deepcopy(centre)
    extended["home"]["incidents"].append(
        {**extended["home"]["incidents"][0], "ws_event_id": 2987999999, "minute": 88, "expanded_minute": 90}
    )
    extended["home"]["stats"]["brandNewStat"] = 3.0
    client.centres[PEN_MATCH] = extended
    fs.sync_match_details(db, client, db.get(Match, match.id))
    assert count(db, MatchIncident) == incidents + 1
    assert db.scalar(select(StatType.id).where(StatType.key == "brandNewStat")) is not None


def test_sync_match_details_statement_budget(db, statements):
    """Round-Trips pro Spiel sind unabhängig von Spieler-/Statistikanzahl (Remote-DB mit Latenz)."""
    seed_matches(
        db,
        [finished_fixture(PEN_MATCH, 36, "Leverkusen", 8), finished_fixture(OWN_GOAL_MATCH, 38, "Hamburg", 9)],
    )
    client = FakeClient(centres={PEN_MATCH: centre_penalty(), OWN_GOAL_MATCH: centre_own_goal()})
    match_id = get_match(db, PEN_MATCH).id
    second_id = get_match(db, OWN_GOAL_MATCH).id
    db.expire_all()
    statements.clear()

    # Erster Sync in leerer Datenbank (Worst Case: alle Stammdaten werden neu angelegt)
    first = fs.sync_match_details(db, client, db.get(Match, match_id), final=True)
    assert first["status"] == "ok"
    first_count = len(statements)
    print(f"Statements erster Sync (leere DB): {first_count}")
    assert first_count <= 28, statements

    # Re-Sync desselben Spiels
    db.expire_all()
    statements.clear()
    again = fs.sync_match_details(db, client, db.get(Match, match_id), final=True)
    assert again["status"] == "ok"
    resync_count = len(statements)
    print(f"Statements Re-Sync: {resync_count}")
    assert resync_count <= 17, statements
    # Re-Sync ohne Änderungen schreibt nur den Sync-Stand
    writes = [s for s in statements if s.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE"))]
    assert len(writes) <= 2, writes

    # Erster Sync eines weiteren Spiels (Spieler/Stat-Typen/Stadion existieren großteils schon)
    db.expire_all()
    statements.clear()
    second = fs.sync_match_details(db, client, db.get(Match, second_id), final=True)
    assert second["status"] == "ok"
    print(f"Statements erster Sync (befüllte DB): {len(statements)}")
    assert len(statements) <= 28, statements


def test_sync_match_details_unavailable_records_attempt(db):
    fixture = make_fixture(1995471, id=PEN_MATCH, homeTeamId=1211, homeTeamName="Hoffenheim",
                           awayTeamId=36, awayTeamName="Leverkusen", startTimeUtc="2026-11-01T14:30:00Z")
    seed_matches(db, [fixture])
    match = get_match(db, PEN_MATCH)
    match_id = match.id
    client = FakeClient(centres={PEN_MATCH: None})
    for expected_attempts in (1, 2):
        result = fs.sync_match_details(db, client, db.get(Match, match_id))
        assert result == {"status": "unavailable"}
        state = db.get(MatchSyncState, match_id)
        db.refresh(state)
        assert state.attempts == expected_attempts
        assert state.last_attempt_at is not None
        assert state.details_synced_at is None
    assert count(db, Appearance) == 0


def test_sync_match_details_client_error_is_recorded_not_raised(db):
    match, _ = _seed_pen_match(db)
    match_id = match.id
    client = FakeClient(centres={PEN_MATCH: WhoScoredError("Timeout")})
    result = fs.sync_match_details(db, client, match)
    assert result["status"] == "error" and "Timeout" in result["error"]
    state = db.get(MatchSyncState, match_id)
    db.refresh(state)
    assert state.attempts == 1 and "Timeout" in state.last_error


def test_sync_match_details_failure_rolls_back_only_that_match(db):
    seasons_fixtures = [
        finished_fixture(PEN_MATCH, 36, "Leverkusen", 8),
        finished_fixture(OWN_GOAL_MATCH, 38, "Hamburg", 9),
    ]
    seed_matches(db, seasons_fixtures)
    # Falsches Match Centre: Teams gehören nicht zu Spiel PEN_MATCH
    client = FakeClient(centres={PEN_MATCH: centre_own_goal(), OWN_GOAL_MATCH: centre_own_goal()})
    bad = fs.sync_match_details(db, client, get_match(db, PEN_MATCH))
    assert bad["status"] == "error"
    assert count(db, Appearance) == 0 and count(db, Player) == 0 and count(db, Venue) == 0
    bad_state = db.get(MatchSyncState, get_match(db, PEN_MATCH).id)
    db.refresh(bad_state)
    assert bad_state.attempts == 1 and bad_state.last_error and bad_state.details_synced_at is None

    good = fs.sync_match_details(db, client, get_match(db, OWN_GOAL_MATCH))
    assert good["status"] == "ok"
    assert count(db, Appearance) == good["appearances"]


def test_sync_match_details_unknown_incident_player_gets_placeholder(db):
    fixture = finished_fixture(PEN_MATCH, 36, "Leverkusen", 8)
    seed_matches(db, [fixture])
    centre = centre_penalty()
    ghost = 999999
    centre["home"]["incidents"][0]["ws_player_id"] = ghost
    client = FakeClient(centres={PEN_MATCH: centre})
    assert fs.sync_match_details(db, client, get_match(db, PEN_MATCH))["status"] == "ok"
    player = db.scalars(select(Player).where(Player.ws_player_id == ghost)).one()
    assert player.name == f"Unbekannt ({ghost})"


# ---------------------------------------------------------------------------
# sync_missing_players
# ---------------------------------------------------------------------------

def _preview() -> dict:
    return parse_missing_players_html((FIXTURE_DIR / "preview_missing_players.html").read_text(encoding="utf-8"))


def _seed_bayern_matches(db):
    first = make_fixture(1995471)  # Bayern (37) vs Köln (282), 20.11.2026
    later = make_fixture(
        1995471, id=1995999, startTimeUtc="2026-11-28T14:30:00Z"
    )  # gleiche Teams, späteres Spiel
    seed_matches(db, [first, later])
    return get_match(db, 1995471), get_match(db, 1995999)


def test_sync_missing_players_inserts_and_replaces(db):
    match, _later = _seed_bayern_matches(db)
    match_id = match.id
    preview = _preview()
    client = FakeClient(previews={1995471: preview})

    result = fs.sync_missing_players(db, client, match)
    assert result == {"status": "ok", "home": 5, "away": 6, "removed": 0}
    assert count(db, MissingPlayer) == 11
    assert db.get(MatchSyncState, match_id).prematch_synced_at is not None
    row = db.scalars(
        select(MissingPlayer).join(Player, Player.id == MissingPlayer.player_id).where(Player.ws_player_id == 335756)
    ).one()
    assert (row.reason, row.status, row.match_id) == ("unfit", "Doubtful", match_id)

    # idempotent
    again = fs.sync_missing_players(db, client, db.get(Match, match_id))
    assert again == {"status": "ok", "home": 5, "away": 6, "removed": 0}
    assert count(db, MissingPlayer) == 11

    # Heim-Spieler (Neuer) wieder fit, Gast-Spieler Status ändert sich
    changed = copy.deepcopy(preview)
    changed["home"] = [p for p in changed["home"] if p["ws_player_id"] != 13754]
    client.previews[1995471] = changed
    result = fs.sync_missing_players(db, client, db.get(Match, match_id))
    assert result == {"status": "ok", "home": 4, "away": 6, "removed": 1}
    assert count(db, MissingPlayer) == 10
    assert db.scalars(
        select(MissingPlayer).join(Player, Player.id == MissingPlayer.player_id).where(Player.ws_player_id == 13754)
    ).first() is None
    # Gegner-Team unverändert
    away_team = db.scalars(select(Team).where(Team.ws_team_id == 282)).one()
    assert db.scalar(select(func.count()).select_from(MissingPlayer).where(MissingPlayer.team_id == away_team.id)) == 6


def test_sync_missing_players_empty_list_clears_team(db):
    match, _ = _seed_bayern_matches(db)
    match_id = match.id
    preview = _preview()
    client = FakeClient(previews={1995471: preview})
    fs.sync_missing_players(db, client, match)
    client.previews[1995471] = {"home": [], "away": preview["away"]}
    result = fs.sync_missing_players(db, client, db.get(Match, match_id))
    assert result == {"status": "ok", "home": 0, "away": 6, "removed": 5}
    assert count(db, MissingPlayer) == 6


def test_sync_missing_players_older_preview_does_not_overwrite_newer(db):
    earlier, later = _seed_bayern_matches(db)
    earlier_id, later_id = earlier.id, later.id
    full = _preview()
    only_neuer = {"home": [p for p in full["home"] if p["ws_player_id"] == 13754], "away": []}
    client = FakeClient(previews={1995999: only_neuer, 1995471: full})

    assert fs.sync_missing_players(db, client, db.get(Match, later_id))["status"] == "ok"
    assert count(db, MissingPlayer) == 1

    # Vorschau des früheren Spiels darf die Daten des späteren nicht überschreiben
    result = fs.sync_missing_players(db, client, db.get(Match, earlier_id))
    assert result["status"] == "ok"
    assert result["removed"] == 0
    assert count(db, MissingPlayer) == 1
    assert db.scalars(select(MissingPlayer)).one().match_id == later_id
    state = db.get(MatchSyncState, earlier_id)
    assert state.prematch_synced_at is not None  # Abruf selbst wurde dennoch vermerkt


def test_sync_missing_players_later_preview_replaces_earlier(db):
    earlier, later = _seed_bayern_matches(db)
    earlier_id, later_id = earlier.id, later.id
    full = _preview()
    only_neuer = {"home": [p for p in full["home"] if p["ws_player_id"] == 13754], "away": []}
    client = FakeClient(previews={1995999: only_neuer, 1995471: full})
    fs.sync_missing_players(db, client, db.get(Match, earlier_id))
    assert count(db, MissingPlayer) == 11
    result = fs.sync_missing_players(db, client, db.get(Match, later_id))
    assert result == {"status": "ok", "home": 1, "away": 0, "removed": 10}
    row = db.scalars(select(MissingPlayer)).one()
    assert row.match_id == later_id


def test_sync_missing_players_error_keeps_existing_data(db):
    match, _ = _seed_bayern_matches(db)
    match_id = match.id
    client = FakeClient(previews={1995471: _preview()})
    fs.sync_missing_players(db, client, match)
    client.previews[1995471] = WhoScoredError("Seite nicht gefunden")
    result = fs.sync_missing_players(db, client, db.get(Match, match_id))
    assert result["status"] == "error"
    assert count(db, MissingPlayer) == 11


def test_sync_missing_players_skips_finished_match(db):
    seed_matches(db, [finished_fixture(PEN_MATCH, 36, "Leverkusen", 8)])
    client = FakeClient(previews={PEN_MATCH: _preview()})
    result = fs.sync_missing_players(db, client, get_match(db, PEN_MATCH))
    assert result["status"] == "skipped"
    assert client.count("missing_players") == 0
    assert count(db, MissingPlayer) == 0


# ---------------------------------------------------------------------------
# sync_prematch
# ---------------------------------------------------------------------------

def test_sync_prematch_with_preview(db):
    fixture = make_fixture(1995471)
    season, seed_client = seed_matches(db, [fixture])
    match = get_match(db, 1995471)
    client = FakeClient(
        fixtures={(STAGE_WS_ID, 2026, 11): [fixture]},
        previews={1995471: _preview()},
        centres={1995471: None},
    )
    result = fs.sync_prematch(db, client, match)
    assert result["fixture"]["unchanged"] == 1 and result["fixture"]["pages"] == 1
    assert result["missing_players"]["status"] == "ok"
    assert result["details"] == {"status": "unavailable"}
    assert client.pages_loaded == 3  # Fixtures-Monat + Preview + Match Centre
    assert count(db, MissingPlayer) == 11


def test_sync_prematch_without_preview_skips_missing_players(db):
    fixture = make_fixture(1995471, hasPreview=False)
    seed_matches(db, [fixture])
    match = get_match(db, 1995471)
    client = FakeClient(fixtures={(STAGE_WS_ID, 2026, 11): [fixture]}, centres={1995471: None})
    result = fs.sync_prematch(db, client, match)
    assert result["missing_players"]["status"] == "skipped"
    assert client.count("missing_players") == 0
    assert count(db, MissingPlayer) == 0


def test_sync_prematch_stores_lineups_when_available(db):
    fixture = finished_fixture(PEN_MATCH, 36, "Leverkusen", 8)
    fixture = dict(fixture, status="scheduled", has_preview=False)
    seed_matches(db, [fixture])
    match = get_match(db, PEN_MATCH)
    client = FakeClient(fixtures={(STAGE_WS_ID, 2026, 11): [fixture]}, centres={PEN_MATCH: centre_penalty()})
    result = fs.sync_prematch(db, client, match)
    assert result["details"]["status"] == "ok"
    state = db.get(MatchSyncState, get_match(db, PEN_MATCH).id)
    assert state.lineups_confirmed_at is not None


# ---------------------------------------------------------------------------
# import_season / sync_match_by_ws_id
# ---------------------------------------------------------------------------

def _import_client() -> FakeClient:
    fixtures = [
        finished_fixture(PEN_MATCH, 36, "Leverkusen", 8),
        finished_fixture(OWN_GOAL_MATCH, 38, "Hamburg", 9),
        make_fixture(1995471),
    ]
    return FakeClient(
        fixtures={(STAGE_WS_ID, 2026, 11): fixtures},
        centres={PEN_MATCH: centre_penalty(), OWN_GOAL_MATCH: centre_own_goal()},
    )


def test_import_season_is_resumable(db):
    client = _import_client()
    first = fs.import_season(db, LEAGUE, "2627", client=client)
    assert first["fixtures"]["created"] == 3
    assert first["details"] == {"pending": 2, "attempted": 2, "ok": 2, "unavailable": 0, "errors": 0}
    assert client.count("match_centre") == 2
    assert first["pages"] == client.pages_loaded
    assert count(db, Appearance) > 0

    appearances = count(db, Appearance)
    second = fs.import_season(db, LEAGUE, "2627", client=client)
    assert second["fixtures"]["created"] == 0
    assert second["details"]["pending"] == 0 and second["details"]["attempted"] == 0
    assert client.count("match_centre") == 2  # keine neuen Detail-Abrufe
    assert client.count("season_metadata") == 1  # Saison existiert -> keine Metadaten-Seiten
    assert count(db, Appearance) == appearances


def test_import_season_max_matches_limits_detail_fetches(db):
    client = _import_client()
    first = fs.import_season(db, LEAGUE, "2627", client=client, max_matches=1)
    assert first["details"]["attempted"] == 1 and first["details"]["pending"] == 2
    assert client.count("match_centre") == 1
    second = fs.import_season(db, LEAGUE, "2627", client=client, max_matches=5)
    assert second["details"]["pending"] == 1 and second["details"]["ok"] == 1
    assert client.count("match_centre") == 2


def test_import_season_without_details_and_with_failures(db):
    client = _import_client()
    result = fs.import_season(db, LEAGUE, "2627", with_details=False, client=client)
    assert result["details"]["attempted"] == 0
    assert client.count("match_centre") == 0

    client.centres[PEN_MATCH] = None
    client.centres[OWN_GOAL_MATCH] = WhoScoredError("kaputt")
    result = fs.import_season(db, LEAGUE, "2627", client=client)
    assert result["details"]["unavailable"] == 1 and result["details"]["errors"] == 1
    # nicht abgeschlossene Spiele werden beim nächsten Lauf erneut versucht
    client.centres[PEN_MATCH] = centre_penalty()
    client.centres[OWN_GOAL_MATCH] = centre_own_goal()
    result = fs.import_season(db, LEAGUE, "2627", client=client)
    assert result["details"]["ok"] == 2


def test_import_season_unknown_league_raises(db):
    with pytest.raises(ValueError):
        fs.import_season(db, "XXX-Nope", "2627", client=FakeClient())


def test_sync_match_by_ws_id_unknown_match_raises(db):
    with pytest.raises(ValueError):
        fs.sync_match_by_ws_id(db, 123456789)


def test_sync_match_by_ws_id_uses_own_client(db, monkeypatch):
    seed_matches(db, [finished_fixture(PEN_MATCH, 36, "Leverkusen", 8)])
    fake = FakeClient(centres={PEN_MATCH: centre_penalty()})

    class _Ctx:
        def __enter__(self):
            return fake

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(fs, "WhoScoredClient", lambda *a, **k: _Ctx())
    result = fs.sync_match_by_ws_id(db, PEN_MATCH, final=True)
    assert result["status"] == "ok"
    state = db.get(MatchSyncState, get_match(db, PEN_MATCH).id)
    assert state.details_final_at is not None


def test_get_or_create_sync_state(db):
    seed_matches(db, [make_fixture(1995471)])
    match = get_match(db, 1995471)
    state = fs.get_or_create_sync_state(db, match)
    assert state.match_id == match.id
    assert fs.get_or_create_sync_state(db, match) is state
    db.rollback()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_cli_competitions_lists_registry(capsys):
    from app import football_cli

    assert football_cli.main(["competitions"]) == 0
    out = capsys.readouterr().out
    for key in COMPETITIONS:
        assert key in out


def test_cli_import_season_exit_codes(monkeypatch, capsys):
    from app import football_cli

    calls = {}

    def fake_import(db, league, season, with_details=True, client=None, max_matches=None):
        calls.update(league=league, season=season, with_details=with_details, max_matches=max_matches)
        return {"details": {"errors": 0}}

    monkeypatch.setattr(fs, "import_season", fake_import)
    code = football_cli.main(["import-season", "--league", LEAGUE, "--season", "2627", "--no-details", "--max-matches", "2"])
    assert code == 0
    assert calls == {"league": LEAGUE, "season": "2627", "with_details": False, "max_matches": 2}

    monkeypatch.setattr(fs, "import_season", lambda *a, **k: {"details": {"errors": 1}})
    assert football_cli.main(["import-season", "--league", LEAGUE, "--season", "2627"]) == 1

    def boom(*a, **k):
        raise ValueError("Unbekannter league_key")

    monkeypatch.setattr(fs, "import_season", boom)
    assert football_cli.main(["import-season", "--league", "XXX", "--season", "2627"]) == 1


def test_cli_sync_match_exit_codes(monkeypatch, capsys):
    from app import football_cli

    for status, expected in (("ok", 0), ("unavailable", 2), ("error", 1)):
        monkeypatch.setattr(fs, "sync_match_by_ws_id", lambda db, ws_id, final=False, s=status: {"status": s})
        assert football_cli.main(["sync-match", "--ws-match-id", "5", "--final"]) == expected
    monkeypatch.setattr(
        fs, "sync_match_by_ws_id", lambda *a, **k: (_ for _ in ()).throw(ValueError("nicht in der Datenbank"))
    )
    assert football_cli.main(["sync-match", "--ws-match-id", "5"]) == 1

