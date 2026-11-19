"""Tests der inkrementellen Fußball-Jobs (``app.schedulers.football_jobs``) mit SQLite und Fake-Client."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

import app.schedulers.football_jobs as fj
import app.schedulers.scheduler as scheduler_module
from app.models import Base, Competition, Match, MatchSyncState, Region, Season, Stage, Team
from app.services import football_service as fs
from app.services.datasources.whoscored import BrowserBusyError
from app.services.football_competitions import get_competition_config

BERLIN = ZoneInfo("Europe/Berlin")
NOW = datetime(2026, 11, 21, 17, 30, tzinfo=BERLIN)  # Samstag
LEAGUE = "GER-Bundesliga"


# ---------------------------------------------------------------------------
# Infrastruktur
# ---------------------------------------------------------------------------

class SqlCounter:
    def __init__(self) -> None:
        self.statements: list[str] = []

    @property
    def count(self) -> int:
        return len(self.statements)


@pytest.fixture(autouse=True)
def clean_state():
    fj.reset_schedule_cache()
    scheduler_module._scheduler = None
    yield
    fj.reset_schedule_cache()
    s = scheduler_module._scheduler
    if s is not None and s.running:
        s.shutdown(wait=False)
    scheduler_module._scheduler = None


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def sql(engine):
    counter = SqlCounter()

    @event.listens_for(engine, "before_cursor_execute")
    def _collect(conn, cursor, statement, parameters, context, executemany):
        counter.statements.append(statement)

    return counter


@pytest.fixture
def session_factory(engine):
    return lambda: Session(engine, autoflush=False)


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


def no_db_factory():
    raise AssertionError("DB-Session darf nicht geöffnet werden")


class FakeClient:
    def __init__(self, busy: bool = False, lock_timeout: float | None = None):
        self.busy = busy
        self.lock_timeout = lock_timeout
        self.pages_loaded = 0

    def __enter__(self):
        if self.busy:
            raise BrowserBusyError("belegt")
        return self

    def __exit__(self, *args):
        return False


class ClientFactory:
    def __init__(self, busy: bool = False):
        self.busy = busy
        self.instances: list[FakeClient] = []

    def __call__(self, lock_timeout=None):
        client = FakeClient(self.busy, lock_timeout)
        self.instances.append(client)
        return client


@pytest.fixture
def factory():
    return ClientFactory()


def seed_base(db) -> Stage:
    region = Region(ws_region_id=81, name="Germany")
    db.add(region)
    db.flush()
    competition = Competition(
        ws_tournament_id=3, region_id=region.id, league_key=LEAGUE, name="Bundesliga", slug="bundesliga", format="league"
    )
    db.add(competition)
    db.flush()
    season = Season(competition_id=competition.id, ws_season_id=9999, code="2627")
    db.add(season)
    db.flush()
    stage = Stage(season_id=season.id, ws_stage_id=1000, is_default=True)
    db.add_all([stage, Team(ws_team_id=1, name="A"), Team(ws_team_id=2, name="B")])
    db.commit()
    return stage


_counter = {"n": 0}


def add_match(db, stage: Stage, kickoff: datetime, status: str = "scheduled", **state) -> Match:
    _counter["n"] += 1
    match = Match(
        ws_match_id=5000 + _counter["n"],
        stage_id=stage.id,
        home_team_id=1,
        away_team_id=2,
        kickoff_time=kickoff,
        status=status,
    )
    db.add(match)
    db.flush()
    db.add(MatchSyncState(match_id=match.id, **{"attempts": 0, **state}))
    db.commit()
    return match


def warm_cache(session_factory, now=NOW):
    fj._load_cache(session_factory, now)


class Recorder:
    """Ersetzt die Service-Funktionen; protokolliert Aufrufe und simuliert Datenänderungen."""

    def __init__(self, session_factory):
        self.calls: list[tuple] = []
        self.finish_on_poll: set[int] = set()
        self.status_on_poll: dict[int, str] = {}
        self.details_result = "ok"

    def prematch(self, db, client, match, refresh_fixtures=True, has_preview=None):
        self.calls.append(("prematch", match.id, refresh_fixtures))
        client.pages_loaded += 2 if not refresh_fixtures else 3
        state = db.get(MatchSyncState, match.id)
        state.fixture_synced_at = NOW
        state.details_synced_at = NOW
        db.commit()
        return {}

    def stage_month(self, db, client, stage, year, month):
        self.calls.append(("stage_month", stage.id, year, month))
        client.pages_loaded += 1
        for match in db.scalars(select(Match).where(Match.stage_id == stage.id)):
            if match.id in self.finish_on_poll:
                match.status = "finished"
            if match.id in self.status_on_poll:
                match.status = self.status_on_poll[match.id]
            state = db.get(MatchSyncState, match.id)
            state.fixture_synced_at = NOW
        db.commit()
        return {"created": 0, "updated": 0, "unchanged": 0, "newly_finished": [], "pages": 1, "has_preview": {}}

    def details(self, db, client, match, final=False):
        self.calls.append(("details", match.id, final))
        client.pages_loaded += 1
        state = db.get(MatchSyncState, match.id)
        if self.details_result == "ok":
            state.details_synced_at = NOW
            state.last_attempt_at = NOW
            if final:
                state.details_final_at = NOW
        else:
            state.attempts = (state.attempts or 0) + 1
            state.last_attempt_at = NOW
        db.commit()
        return {"status": self.details_result}

    def names(self, name: str) -> list[tuple]:
        return [c for c in self.calls if c[0] == name]


@pytest.fixture
def rec(monkeypatch, session_factory):
    recorder = Recorder(session_factory)
    monkeypatch.setattr(fs, "sync_prematch", recorder.prematch)
    monkeypatch.setattr(fs, "sync_stage_month", recorder.stage_month)
    monkeypatch.setattr(fs, "sync_match_details", recorder.details)
    return recorder


# ---------------------------------------------------------------------------
# Tick: Idle / Prematch / Lineups
# ---------------------------------------------------------------------------

def test_idle_tick_opens_no_client_and_runs_zero_sql(db, session_factory, sql, factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(hours=3))
    add_match(db, stage, NOW - timedelta(days=1), status="finished", details_synced_at=NOW, details_final_at=NOW)
    warm_cache(session_factory)
    sql.statements.clear()

    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory)

    assert result == {"status": "idle"}
    assert factory.instances == []
    assert sql.count == 0


def test_first_tick_loads_cache_with_a_single_query(db, session_factory, sql, factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(hours=3))
    sql.statements.clear()

    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory) == {"status": "idle"}
    assert sql.count == 1
    assert factory.instances == []
    # zweiter Tick: Cache warm -> keine Abfrage mehr
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}
    assert sql.count == 1


def test_prematch_at_t_minus_45_but_not_t_minus_60(db, session_factory, factory, rec):
    stage = seed_base(db)
    early = add_match(db, stage, NOW + timedelta(minutes=60))
    due = add_match(db, stage, NOW + timedelta(minutes=44))
    warm_cache(session_factory)

    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)

    assert result["status"] == "ok"
    assert rec.names("prematch") == [("prematch", due.id, False)]
    assert rec.names("stage_month") == [("stage_month", stage.id, 2026, 11)]
    assert early.id not in {c[1] for c in rec.names("prematch")}
    assert len(factory.instances) == 1 and factory.instances[0].lock_timeout == 0
    assert result["pages_loaded"] == 3

    # Prematch wird nicht wiederholt (auch ohne Preview: Fixture-Sync-Zeitstempel zählt)
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}
    # 16 min später ist das frühe Spiel dran
    later = NOW + timedelta(minutes=16)
    fj.run_matchday_tick(now=later, client_factory=factory, session_factory=session_factory)
    assert rec.names("prematch") == [("prematch", due.id, False), ("prematch", early.id, False)]


def test_prematch_selection_ignores_non_scheduled_and_started(db, session_factory, factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(minutes=30), status="postponed")
    add_match(db, stage, NOW - timedelta(minutes=1))  # Anpfiff schon vorbei (und noch nicht im Post-Match-Fenster)
    warm_cache(session_factory)
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory)["status"] == "idle"


def test_second_lineup_attempt_logic(db, session_factory, factory, rec):
    stage = seed_base(db)
    kickoff = NOW + timedelta(minutes=15)
    prematch_time = kickoff - timedelta(minutes=40)
    due = add_match(
        db, stage, kickoff, fixture_synced_at=prematch_time, prematch_synced_at=prematch_time, details_synced_at=prematch_time
    )
    # Lineups schon bestätigt -> kein Retry
    add_match(
        db, stage, kickoff, fixture_synced_at=prematch_time, details_synced_at=prematch_time, lineups_confirmed_at=prematch_time
    )
    # letzter Detail-Versuch erst bei T-25 -> kein zweiter Versuch
    add_match(db, stage, kickoff, fixture_synced_at=prematch_time, last_attempt_at=kickoff - timedelta(minutes=25))
    warm_cache(session_factory)

    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)

    assert result["lineup_retry"] == 1
    assert rec.calls == [("details", due.id, False)]  # nur Details, kein Prematch/Fixture-Refresh

    # "einmal": Der Versuch ist jetzt vermerkt -> nächster Tick idle
    assert fj.run_matchday_tick(now=NOW + timedelta(minutes=3), client_factory=factory, session_factory=no_db_factory) == {
        "status": "idle"
    }


def test_lineup_retry_only_within_last_20_minutes(db, session_factory, factory, rec):
    stage = seed_base(db)
    kickoff = NOW + timedelta(minutes=30)
    prematch_time = kickoff - timedelta(minutes=44)
    add_match(db, stage, kickoff, fixture_synced_at=prematch_time, details_synced_at=prematch_time)
    warm_cache(session_factory)
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}


# ---------------------------------------------------------------------------
# Tick: Post-Match
# ---------------------------------------------------------------------------

def test_postmatch_groups_parallel_matches_into_one_refresh(db, session_factory, factory, rec):
    stage = seed_base(db)
    other_stage = Stage(season_id=stage.season_id, ws_stage_id=1001)
    db.add(other_stage)
    db.commit()
    kickoff = NOW - timedelta(minutes=110)
    m1 = add_match(db, stage, kickoff)
    m2 = add_match(db, stage, kickoff)
    m3 = add_match(db, stage, kickoff, status="live")
    other = add_match(db, other_stage, kickoff)
    add_match(db, stage, NOW - timedelta(minutes=60), status="live")  # noch zu früh für das Polling
    rec.finish_on_poll = {m1.id, m2.id}
    warm_cache(session_factory)

    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)

    assert result["polled_groups"] == 2
    refreshes = rec.names("stage_month")
    assert sorted(refreshes) == sorted([("stage_month", stage.id, 2026, 11), ("stage_month", other_stage.id, 2026, 11)])
    detail_ids = {c[1] for c in rec.names("details")}
    assert detail_ids == {m1.id, m2.id}  # nur tatsächlich beendete Spiele
    assert m3.id not in detail_ids and other.id not in detail_ids
    assert len(factory.instances) == 1  # genau ein Client/Browser
    assert result["details_ok"] == 2


def test_postmatch_polling_is_throttled_by_fixture_sync_time(db, session_factory, factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW - timedelta(minutes=110), fixture_synced_at=NOW - timedelta(minutes=1))
    warm_cache(session_factory)
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}
    # später im Fenster (>150 min) gilt der 10-min-Takt
    stage_id = stage.id
    fj.reset_schedule_cache()
    with session_factory() as s:
        m = s.scalars(select(Match)).one()
        m.kickoff_time = NOW - timedelta(minutes=200)
        s.get(MatchSyncState, m.id).fixture_synced_at = NOW - timedelta(minutes=5)
        s.commit()
    warm_cache(session_factory)
    assert fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}
    fj.run_matchday_tick(now=NOW + timedelta(minutes=6), client_factory=factory, session_factory=session_factory)
    assert rec.names("stage_month") == [("stage_month", stage_id, 2026, 11)]


def test_tick_retries_finished_match_details_with_attempt_limits(db, session_factory, factory, rec):
    stage = seed_base(db)
    kickoff = NOW - timedelta(hours=2)
    retry = add_match(db, stage, kickoff, status="finished", attempts=1, last_attempt_at=NOW - timedelta(minutes=10))
    add_match(db, stage, kickoff, status="finished", attempts=4, last_attempt_at=NOW - timedelta(minutes=10))  # Tick gibt auf
    add_match(db, stage, kickoff, status="finished", attempts=1, last_attempt_at=NOW - timedelta(minutes=2))  # zu frisch
    warm_cache(session_factory)

    fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)

    assert rec.calls == [("details", retry.id, False)]  # kein Fixture-Refresh nötig


# ---------------------------------------------------------------------------
# Catch-up
# ---------------------------------------------------------------------------

def test_idle_catchup_runs_zero_sql(db, session_factory, sql, factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(hours=2))
    add_match(db, stage, NOW - timedelta(days=1), status="finished", details_synced_at=NOW)
    add_match(db, stage, NOW - timedelta(days=1), status="finished", attempts=8)
    add_match(db, stage, NOW - timedelta(hours=2), status="live")  # noch im Tick-Fenster
    warm_cache(session_factory)
    sql.statements.clear()

    assert fj.run_hourly_catchup(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}
    assert factory.instances == [] and sql.count == 0


def test_catchup_respects_attempts_limit_and_oldest_first(db, session_factory, factory, rec):
    stage = seed_base(db)
    ids = [
        add_match(db, stage, NOW - timedelta(days=2, minutes=i), status="finished", attempts=i % 8).id for i in range(30)
    ]
    exhausted = add_match(db, stage, NOW - timedelta(days=3), status="finished", attempts=8)
    recent = add_match(
        db, stage, NOW - timedelta(days=3), status="finished", attempts=2, last_attempt_at=NOW - timedelta(minutes=10)
    )
    too_old = add_match(db, stage, NOW - timedelta(days=13, hours=23), status="finished")
    warm_cache(session_factory)

    result = fj.run_hourly_catchup(now=NOW, client_factory=factory, session_factory=session_factory)

    called = [c[1] for c in rec.names("details")]
    assert len(called) == fj.CATCHUP_LIMIT == 25
    assert exhausted.id not in called and recent.id not in called
    assert called[0] == too_old.id  # ältestes zuerst
    assert called[1:] == list(reversed(ids))[:24]  # danach nach Anpfiff aufsteigend (i=29 ist am ältesten)
    assert result["details_ok"] == 25
    assert factory.instances[0].lock_timeout == fj.LONG_LOCK_TIMEOUT


def test_catchup_fixes_overdue_matches_once(db, session_factory, factory, rec):
    stage = seed_base(db)
    overdue = add_match(db, stage, NOW - timedelta(hours=7))
    rec.status_on_poll = {overdue.id: "postponed"}
    warm_cache(session_factory)

    first = fj.run_hourly_catchup(now=NOW, client_factory=factory, session_factory=session_factory)
    assert first["refreshed_groups"] == 1
    assert rec.names("stage_month") == [("stage_month", stage.id, 2026, 11)]
    assert rec.names("details") == []
    # Status korrigiert + Fixture nach der Frist synchronisiert -> nichts mehr zu tun
    assert fj.run_hourly_catchup(now=NOW, client_factory=factory, session_factory=no_db_factory) == {"status": "idle"}


def test_catchup_loads_details_for_match_finished_by_status_fix(db, session_factory, factory, rec):
    stage = seed_base(db)
    overdue = add_match(db, stage, NOW - timedelta(hours=8))
    rec.finish_on_poll = {overdue.id}
    warm_cache(session_factory)
    fj.run_hourly_catchup(now=NOW, client_factory=factory, session_factory=session_factory)
    assert rec.names("details") == [("details", overdue.id, False)]


# ---------------------------------------------------------------------------
# Daily / Bootstrap
# ---------------------------------------------------------------------------

class SyncRecorder:
    def __init__(self, season):
        self.season_id = season.id
        self.fixture_calls: list[list | None] = []

    def ensure(self, db, client, league_key, code, refresh=False):
        client.pages_loaded += 1
        return db.get(Season, self.season_id)

    def fixtures(self, db, client, season, months=None):
        self.fixture_calls.append(months)
        client.pages_loaded += 2
        return {}


@pytest.fixture
def daily(monkeypatch, db, rec):
    stage = seed_base(db)
    season = db.get(Season, stage.season_id)
    syncs = SyncRecorder(season)
    monkeypatch.setattr(fs, "ensure_season", syncs.ensure)
    monkeypatch.setattr(fs, "sync_fixtures", syncs.fixtures)
    monkeypatch.setattr(fj, "enabled_competitions", lambda: [get_competition_config(LEAGUE)])
    return SimpleNamespace(stage=stage, syncs=syncs)


def test_daily_bootstraps_empty_season_with_full_sync(daily, session_factory, factory):
    result = fj.run_daily_sync(now=NOW, client_factory=factory, session_factory=session_factory)
    assert daily.syncs.fixture_calls == [None]
    assert result["full"] == 1 and result["pages_loaded"] == 3
    assert fj.schedule_cache_loaded()


def test_daily_incremental_months_current_and_next(daily, db, session_factory, factory):
    add_match(db, daily.stage, NOW + timedelta(days=1))
    fj.run_daily_sync(now=NOW, client_factory=factory, session_factory=session_factory)  # Samstag, 21.
    assert daily.syncs.fixture_calls == [[(2026, 11), (2026, 12)]]


def test_daily_includes_previous_month_until_the_7th(daily, db, session_factory, factory):
    add_match(db, daily.stage, NOW + timedelta(days=1))
    fj.run_daily_sync(now=datetime(2027, 1, 7, 4, 0, tzinfo=BERLIN), client_factory=factory, session_factory=session_factory)
    fj.run_daily_sync(now=datetime(2027, 1, 8, 4, 0, tzinfo=BERLIN), client_factory=factory, session_factory=session_factory)
    assert daily.syncs.fixture_calls == [[(2026, 12), (2027, 1), (2027, 2)], [(2027, 1), (2027, 2)]]


def test_incremental_months_year_wrap():
    assert fj.incremental_months(datetime(2026, 12, 3, tzinfo=BERLIN)) == [(2026, 11), (2026, 12), (2027, 1)]
    assert fj.incremental_months(datetime(2026, 12, 20, tzinfo=BERLIN)) == [(2026, 12), (2027, 1)]


def test_daily_monday_does_full_calendar_refresh(daily, db, session_factory, factory):
    add_match(db, daily.stage, NOW + timedelta(days=1))
    fj.run_daily_sync(now=datetime(2026, 11, 23, 4, 0, tzinfo=BERLIN), client_factory=factory, session_factory=session_factory)
    assert daily.syncs.fixture_calls == [None]


def test_daily_final_reload_selection(daily, db, session_factory, factory, rec):
    stage = daily.stage
    add_match(db, stage, NOW + timedelta(days=1))  # damit die Saison nicht leer ist
    selected = add_match(db, stage, NOW - timedelta(hours=7), status="finished", details_synced_at=NOW - timedelta(hours=4))
    add_match(db, stage, NOW - timedelta(hours=2), status="finished", details_synced_at=NOW - timedelta(hours=1))  # zu früh
    add_match(db, stage, NOW - timedelta(days=2), status="finished", details_synced_at=NOW, details_final_at=NOW)  # fertig
    add_match(db, stage, NOW - timedelta(days=2), status="finished")  # noch keine Details -> Catch-up
    add_match(db, stage, NOW - timedelta(days=15), status="finished", details_synced_at=NOW - timedelta(days=14))  # zu alt

    result = fj.run_daily_sync(now=NOW, client_factory=factory, session_factory=session_factory)

    assert rec.calls == [("details", selected.id, True)]
    assert result["finals"] == 1


def test_bootstrap_skips_when_season_has_matches(daily, db, session_factory, sql, factory):
    add_match(db, daily.stage, NOW + timedelta(days=1))
    result = fj.run_bootstrap(now=NOW, client_factory=factory, session_factory=session_factory)
    assert result == {"status": "idle"}
    assert factory.instances == [] and daily.syncs.fixture_calls == []
    assert fj.schedule_cache_loaded()


def test_bootstrap_fills_empty_current_season_only(daily, session_factory, factory, rec):
    result = fj.run_bootstrap(now=NOW, client_factory=factory, session_factory=session_factory)
    assert daily.syncs.fixture_calls == [None]
    assert result["full"] == 1
    assert rec.calls == []  # kein finaler Detail-Nachlauf im Bootstrap


def test_bootstrap_with_missing_season_row(monkeypatch, db, session_factory, factory):
    monkeypatch.setattr(fj, "enabled_competitions", lambda: [get_competition_config(LEAGUE)])
    seen = []

    def fake_ensure(db_, client, league_key, code, refresh=False):
        seen.append((league_key, code))
        return seed_base(db_).season

    monkeypatch.setattr(fs, "ensure_season", fake_ensure)
    monkeypatch.setattr(fs, "sync_fixtures", lambda *a, **k: seen.append(("fixtures", k.get("months"))) or {})
    result = fj.run_bootstrap(now=NOW, client_factory=factory, session_factory=session_factory)
    assert seen[0] == (LEAGUE, "2627") and seen[1] == ("fixtures", None)
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Browser belegt / Advisory-Lock
# ---------------------------------------------------------------------------

def test_browser_busy_skips_without_exception(db, session_factory, rec):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(minutes=30))
    warm_cache(session_factory)
    busy = ClientFactory(busy=True)

    assert fj.run_matchday_tick(now=NOW, client_factory=busy, session_factory=session_factory) == {"status": "busy"}
    assert rec.calls == []
    assert fj.run_daily_sync(now=NOW, client_factory=busy, session_factory=session_factory) == {"status": "busy"}
    assert busy.instances[0].lock_timeout == 0
    assert busy.instances[1].lock_timeout == fj.LONG_LOCK_TIMEOUT


def test_failure_in_one_match_does_not_stop_others(db, session_factory, factory, rec, monkeypatch):
    stage = seed_base(db)
    first = add_match(db, stage, NOW + timedelta(minutes=30))
    second = add_match(db, stage, NOW + timedelta(minutes=40))
    warm_cache(session_factory)

    def flaky(db_, client, match, **kwargs):
        if match.id == first.id:
            raise RuntimeError("kaputt")
        return rec.prematch(db_, client, match, **kwargs)

    monkeypatch.setattr(fs, "sync_prematch", flaky)
    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)
    assert result["status"] == "ok"
    assert rec.names("prematch") == [("prematch", second.id, False)]


def test_scraper_db_lock_is_noop_on_sqlite(db):
    with fj.scraper_db_lock(db) as acquired:
        assert acquired is True


class _FakeConn:
    def __init__(self, acquired: bool):
        self.acquired = acquired
        self.sql: list[str] = []
        self.closed = False

    def execute(self, statement, params=None):
        text_ = str(statement)
        self.sql.append(text_)
        return SimpleNamespace(scalar=lambda: self.acquired)

    def close(self):
        self.closed = True

    def invalidate(self):
        pass


def _postgres_db(conn):
    bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"), connect=lambda: conn)
    return SimpleNamespace(get_bind=lambda: bind)


def test_scraper_db_lock_postgres_acquire_and_release():
    conn = _FakeConn(True)
    with fj.scraper_db_lock(_postgres_db(conn)) as acquired:
        assert acquired is True
        assert not conn.closed
    assert [s for s in conn.sql] == ["SELECT pg_try_advisory_lock(:k)", "SELECT pg_advisory_unlock(:k)"]
    assert conn.closed


def test_scraper_db_lock_postgres_not_acquired_skips_job(db, session_factory, factory, rec, monkeypatch):
    stage = seed_base(db)
    add_match(db, stage, NOW + timedelta(minutes=30))
    warm_cache(session_factory)
    conn = _FakeConn(False)

    class PgSession:
        def __init__(self):
            self._inner = session_factory()

        def get_bind(self):
            return _postgres_db(conn).get_bind()

        def __getattr__(self, name):
            return getattr(self._inner, name)

    result = fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=PgSession)
    assert result == {"status": "locked"}
    assert factory.instances == [] and rec.calls == []
    assert conn.sql == ["SELECT pg_try_advisory_lock(:k)"] and conn.closed


# ---------------------------------------------------------------------------
# Registrierung im Scheduler
# ---------------------------------------------------------------------------

FOOTBALL_JOB_IDS = {"football_daily_sync", "football_matchday_tick", "football_hourly_catchup", "football_bootstrap"}


def test_start_scheduler_registers_football_jobs_when_enabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "whoscored_enabled", True)
    scheduler_module.start_scheduler()
    jobs = {j.id: j for j in scheduler_module.get_scheduler().get_jobs()}
    assert FOOTBALL_JOB_IDS <= set(jobs)
    assert {"nightly_session_status_update", "hourly_f1_data_fetch"} <= set(jobs)
    for job_id in FOOTBALL_JOB_IDS - {"football_bootstrap"}:
        assert jobs[job_id].max_instances == 1 and jobs[job_id].coalesce is True
    assert "cron" in str(jobs["football_daily_sync"].trigger) and "hour='4'" in str(jobs["football_daily_sync"].trigger)
    assert "minute='17'" in str(jobs["football_hourly_catchup"].trigger)
    assert "0:03:00" in str(jobs["football_matchday_tick"].trigger)
    assert "date" in str(jobs["football_bootstrap"].trigger)


def test_start_scheduler_skips_football_jobs_when_disabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "whoscored_enabled", False)
    scheduler_module.start_scheduler()
    job_ids = {j.id for j in scheduler_module.get_scheduler().get_jobs()}
    assert not (FOOTBALL_JOB_IDS & job_ids)
    assert "hourly_f1_data_fetch" in job_ids


def test_architecture_graph_has_football_jobs_and_no_match_monitor():
    from app.web.metadata import get_architecture_graph

    graph = get_architecture_graph()
    node_ids = {n["data"]["id"] for n in graph["nodes"]}
    assert {f"job:{j}" for j in FOOTBALL_JOB_IDS} <= node_ids
    assert "job:match_monitor" not in node_ids
    for edge in graph["edges"]:
        assert edge["data"]["source"] in node_ids and edge["data"]["target"] in node_ids


# ---------------------------------------------------------------------------
# Service: sync_stage_month
# ---------------------------------------------------------------------------

def test_sync_stage_month_loads_only_that_stage_and_month(db):
    from tests.test_football_service import STAGE_WS_ID, FakeClient, finished_fixture

    fixtures = {(STAGE_WS_ID, 2026, 11): [finished_fixture(1900101, 36, "Leverkusen", 8)]}
    seed_client = FakeClient(fixtures=fixtures, stage_ws_ids=(STAGE_WS_ID, 25667))
    season = fs.ensure_season(db, seed_client, LEAGUE, "2627")
    fs.sync_fixtures(db, seed_client, season)

    client = FakeClient(fixtures=fixtures, stage_ws_ids=(STAGE_WS_ID, 25667))
    stage = db.scalars(select(Stage).where(Stage.ws_stage_id == STAGE_WS_ID)).one()
    result = fs.sync_stage_month(db, client, stage, 2026, 11)

    assert client.calls == [("fixtures_month", STAGE_WS_ID, 2026, 11)]
    assert result["pages"] == 1
    assert (result["created"], result["unchanged"]) == (0, 1)
    assert set(result["has_preview"]) == {1900101}


def _upcoming_fixture(ws_match_id: int, away_id: int, away_name: str, kickoff_utc: str) -> dict:
    from tests.test_football_service import make_fixture

    return make_fixture(
        1995458,
        id=ws_match_id,
        homeTeamId=1211,
        homeTeamName="Hoffenheim",
        awayTeamId=away_id,
        awayTeamName=away_name,
        startTimeUtc=kickoff_utc,
        startedAtUtc=None,
        firstHalfEndedAtUtc=None,
        secondHalfStartedAtUtc=None,
        status=1,
        elapsed="",
        hasPreview=True,
        homeScore=None,
        awayScore=None,
    )


def test_prematch_group_loads_one_fixture_page_for_three_matches(db, session_factory):
    """3 parallele Spiele (gleicher Stage-Monat): 1 Fixture-Seite + 3 Previews + 3 Match-Centre-Versuche."""
    from tests.test_football_service import STAGE_WS_ID, FakeClient

    kickoff_utc = "2026-11-21T17:00:00Z"  # 18:00 Berlin = NOW + 30 min
    fixtures = {
        (STAGE_WS_ID, 2026, 11): [
            _upcoming_fixture(1900201, 36, "Leverkusen", kickoff_utc),
            _upcoming_fixture(1900202, 38, "Hamburg", kickoff_utc),
            _upcoming_fixture(1900203, 39, "Bremen", kickoff_utc),
        ]
    }
    previews = {ws_id: {"home": [], "away": []} for ws_id in (1900201, 1900202, 1900203)}

    class ContextClient(FakeClient):
        def __call__(self, lock_timeout=None):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    client = ContextClient(fixtures=fixtures, previews=previews)
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    fs.sync_fixtures(db, client, season)
    # Fixture-Sync-Zeitstempel zurücksetzen (unabhängig von der echten Uhrzeit) und Zähler leeren
    for state in db.scalars(select(MatchSyncState)):
        state.fixture_synced_at = None
    db.commit()
    client.calls.clear()
    client.pages_loaded = 0
    warm_cache(session_factory)

    result = fj.run_matchday_tick(now=NOW, client_factory=client, session_factory=session_factory)

    assert result["status"] == "ok" and result["prematch"] == 3
    assert client.count("fixtures_month") == 1
    assert client.count("missing_players") == 3
    assert client.count("match_centre") == 3
    assert client.pages_loaded == 7 == result["pages_loaded"]
    db.expire_all()
    assert all(s.prematch_synced_at is not None for s in db.scalars(select(MatchSyncState)))


def test_sync_prematch_without_fixture_refresh_uses_given_preview_flag(db):
    from tests.test_football_service import STAGE_WS_ID, FakeClient

    fixtures = {(STAGE_WS_ID, 2026, 11): [_upcoming_fixture(1900301, 36, "Leverkusen", "2026-11-21T17:00:00Z")]}
    client = FakeClient(fixtures=fixtures, previews={1900301: {"home": [], "away": []}})
    season = fs.ensure_season(db, client, LEAGUE, "2627")
    fs.sync_fixtures(db, client, season)
    match = db.scalars(select(Match)).one()
    client.calls.clear()

    result = fs.sync_prematch(db, client, match, refresh_fixtures=False, has_preview=True)
    assert result["fixture"]["status"] == "skipped"
    assert [c[0] for c in client.calls] == ["missing_players", "match_centre"]

    client.calls.clear()
    result = fs.sync_prematch(db, client, match, refresh_fixtures=False)
    assert result["missing_players"]["reason"] == "no_preview"
    assert [c[0] for c in client.calls] == ["match_centre"]



# ---------------------------------------------------------------------------
# Service: Versuchszähler vor/nach Anpfiff
# ---------------------------------------------------------------------------

def test_prematch_details_attempt_does_not_consume_attempt_budget(db, session_factory):
    from app.services.datasources.whoscored import WhoScoredError
    from tests.test_football_service import FakeClient

    stage = seed_base(db)
    real_now = datetime.now(BERLIN)
    upcoming = add_match(db, stage, real_now + timedelta(minutes=30))
    client = FakeClient(centres={upcoming.ws_match_id: None})

    assert fs.sync_match_details(db, client, upcoming) == {"status": "unavailable"}
    state = db.get(MatchSyncState, upcoming.id)
    db.refresh(state)
    assert state.attempts == 0 and state.last_error is None
    assert state.last_attempt_at is not None and state.details_synced_at is None

    # echte Fehler werden vermerkt, zählen aber ebenfalls nicht
    client.centres[upcoming.ws_match_id] = WhoScoredError("Timeout")
    assert fs.sync_match_details(db, client, db.get(Match, upcoming.id))["status"] == "error"
    db.refresh(state)
    assert state.attempts == 0 and "Timeout" in state.last_error

    # Cache + zweiter Aufstellungsversuch hängen an last_attempt_at (nicht an attempts)
    fj.refresh_schedule_cache(db, real_now)
    entry = fj.get_schedule_cache()[0]
    assert entry.attempts == 0 and entry.last_attempt_at is not None


def test_postmatch_unavailable_increments_attempts(db):
    from tests.test_football_service import FakeClient

    stage = seed_base(db)
    real_now = datetime.now(BERLIN)
    started = add_match(db, stage, real_now - timedelta(minutes=10))  # Anpfiff erreicht, Status noch "scheduled"
    finished = add_match(db, stage, real_now - timedelta(hours=3), status="finished")
    client = FakeClient(centres={started.ws_match_id: None, finished.ws_match_id: None})

    for match in (started, finished):
        assert fs.sync_match_details(db, client, db.get(Match, match.id)) == {"status": "unavailable"}
        state = db.get(MatchSyncState, match.id)
        db.refresh(state)
        assert state.attempts == 1 and state.last_error == "Match Centre nicht verfügbar"
        assert state.last_attempt_at is not None


def test_lineup_retry_still_planned_after_unavailable_prematch_attempt(db, session_factory, factory, rec):
    """Der Vorab-Versuch setzt last_attempt_at (nicht attempts); Retry-Logik nutzt nur Zeitstempel."""
    stage = seed_base(db)
    kickoff = NOW + timedelta(minutes=15)
    early = kickoff - timedelta(minutes=40)
    match = add_match(db, stage, kickoff, fixture_synced_at=early, last_attempt_at=early, attempts=0)
    warm_cache(session_factory)
    fj.run_matchday_tick(now=NOW, client_factory=factory, session_factory=session_factory)
    assert rec.calls == [("details", match.id, False)]
