"""Inkrementelle WhoScored-Fußball-Jobs (ein Browser zur Zeit, DB nur bei fälligem Plan).

Jobs (Registrierung über ``register_jobs`` aus ``start_scheduler``):

* ``football_daily_sync``     – 04:00 Berlin: Spielpläne (inkrementell/Bootstrap/montags komplett),
                                finaler Nachlade-Lauf der Match-Details.
* ``football_matchday_tick``  – alle 3 Minuten: Prematch (T-45 min), zweiter Aufstellungsversuch (T-20 min),
                                Polling nach Spielende + sofortiger Detail-Abruf. Entscheidet NUR aus dem
                                In-Memory-Spielplan-Cache (0 DB-Abfragen, solange nichts fällig ist).
* ``football_hourly_catchup`` – Minute 17 jeder Stunde: Details nachladen, hängengebliebene Spiele korrigieren.
                                Entscheidet ebenfalls zuerst aus dem Cache.
* ``football_bootstrap``      – einmalig ~60 s nach Start: füllt Wettbewerbe, deren aktuelle Saison leer ist.

Kostenregel (Neon Free): Die DB darf nur um Spielzeitfenster herum geweckt werden. Darum liegt der
Spielplan der nächsten/letzten Tage als leichtgewichtige Liste im Speicher; die DB wird nur gelesen
(a) im Daily-Sync, (b) beim Bootstrap/ersten Tick, (c) nach einem Lauf, der tatsächlich gescrapt hat.

Alle Funktionen nehmen ``now``, ``client_factory`` und ``session_factory`` entgegen (Tests). Pro Lauf wird
höchstens EIN ``WhoScoredClient`` geöffnet (Browser startet erst beim ersten Seitenabruf). Bei PostgreSQL
verhindert ein Advisory-Lock (``scraper_db_lock``), dass zwei Prozesse (z. B. lokaler Worker + Render)
gleichzeitig gegen dieselbe DB scrapen.
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Iterator
from zoneinfo import ZoneInfo

from sqlalchemy import select, text

from app.logging_config import get_logger
from app.models import Competition, Match, MatchSyncState, Season, Stage
from app.services import football_service as fs
from app.services.datasources.whoscored import BrowserBusyError, WhoScoredClient
from app.services.football_competitions import current_season_code, enabled_competitions

logger = get_logger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")

# --- Zeitfenster / Schwellwerte -------------------------------------------------------------------
PREMATCH_LEAD = timedelta(minutes=45)  # Prematch ab 45 min vor Anpfiff
LINEUP_RETRY_LEAD = timedelta(minutes=20)  # zweiter Aufstellungsversuch ab 20 min vor Anpfiff
LINEUP_RETRY_MIN_AGE = timedelta(minutes=30)  # nur, wenn der letzte Detail-Versuch älter als T-30 min ist
POSTMATCH_START = timedelta(minutes=105)  # frühestes Polling: Anpfiff + 105 min
POSTMATCH_END = timedelta(hours=6)  # danach übernimmt der stündliche Catch-up
POSTMATCH_FAST_UNTIL = timedelta(minutes=150)  # bis dahin Polling im Takt des Ticks, danach seltener
POLL_GAP_FAST = timedelta(minutes=2)
POLL_GAP_SLOW = timedelta(minutes=10)
DETAIL_RETRY_GAP = timedelta(minutes=5)  # Abstand zwischen Detail-Versuchen im Tick
TICK_MAX_ATTEMPTS = 4  # Tick gibt nach 4 Versuchen auf (Rest: Catch-up, 4 weitere Versuche)
CATCHUP_MAX_ATTEMPTS = 8  # danach wird nicht mehr versucht (z. B. DFB-Pokal ohne Match Centre)
CATCHUP_RETRY_GAP = timedelta(minutes=30)
CATCHUP_LIMIT = 25
CATCHUP_LOOKBACK = timedelta(days=14)
FINAL_RELOAD_AFTER = timedelta(hours=6)
CACHE_PAST = timedelta(days=14)
CACHE_FUTURE = timedelta(days=8)

TICK_LOCK_TIMEOUT = 0
LONG_LOCK_TIMEOUT = 600

# Konstante für pg_try_advisory_lock (beliebiger bigint, projektweit eindeutig)
SCRAPER_ADVISORY_LOCK_KEY = 7_315_204_118

SessionFactory = Callable[[], Any]
ClientFactory = Callable[..., Any]


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _berlin(value: datetime | None) -> datetime | None:
    """Vereinheitlicht Zeitstempel (SQLite liefert naive Werte = Berliner Wandzeit)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BERLIN)
    return value.astimezone(BERLIN)


def _now(now: datetime | None) -> datetime:
    return _berlin(now) if now is not None else datetime.now(BERLIN)


def _default_session_factory() -> Any:
    from app.database.session import SessionLocal

    return SessionLocal()


@contextmanager
def scraper_db_lock(db: Any) -> Iterator[bool]:
    """Prozessübergreifender Scraper-Lock über ``pg_try_advisory_lock`` (nur PostgreSQL).

    Liefert ``True``, wenn der Lock gehalten wird (bzw. bei SQLite immer), sonst ``False`` – dann muss
    der Lauf übersprungen werden. Der Lock liegt auf einer eigenen Verbindung und wird am Ende wieder
    freigegeben. Hinweis: Session-Locks funktionieren nicht über einen Transaction-Pooler (pgbouncer
    im Transaction-Mode); bei Neon dafür die direkte (nicht gepoolte) Verbindung verwenden.
    """
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        yield True
        return

    conn = bind.connect()
    try:
        acquired = bool(conn.execute(text("SELECT pg_try_advisory_lock(:k)"), {"k": SCRAPER_ADVISORY_LOCK_KEY}).scalar())
        try:
            yield acquired
        finally:
            if acquired:
                try:
                    conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": SCRAPER_ADVISORY_LOCK_KEY})
                except Exception:  # noqa: BLE001 – Verbindung verwerfen, damit der Lock sicher verfällt
                    logger.warning("Advisory-Lock konnte nicht freigegeben werden – Verbindung wird verworfen")
                    conn.invalidate()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Spielplan-Cache (In-Memory)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ScheduleEntry:
    match_id: int
    stage_id: int
    kickoff_time: datetime
    status: str
    fixture_synced_at: datetime | None = None
    prematch_synced_at: datetime | None = None
    lineups_confirmed_at: datetime | None = None
    details_synced_at: datetime | None = None
    details_final_at: datetime | None = None
    last_attempt_at: datetime | None = None
    attempts: int = 0

    @property
    def month_key(self) -> tuple[int, int, int]:
        return (self.stage_id, self.kickoff_time.year, self.kickoff_time.month)


_cache_lock = threading.RLock()
_cache: list[ScheduleEntry] = []
_cache_loaded = False


def refresh_schedule_cache(db: Any, now: datetime | None = None) -> int:
    """Lädt die Spiele mit Anpfiff in ``[now-14d, now+8d]`` neu in den Cache (eine Abfrage)."""
    now = _now(now)
    rows = db.execute(
        select(
            Match.id,
            Match.stage_id,
            Match.kickoff_time,
            Match.status,
            MatchSyncState.fixture_synced_at,
            MatchSyncState.prematch_synced_at,
            MatchSyncState.lineups_confirmed_at,
            MatchSyncState.details_synced_at,
            MatchSyncState.details_final_at,
            MatchSyncState.last_attempt_at,
            MatchSyncState.attempts,
        )
        .outerjoin(MatchSyncState, MatchSyncState.match_id == Match.id)
        .where(Match.kickoff_time >= now - CACHE_PAST, Match.kickoff_time <= now + CACHE_FUTURE)
    ).all()
    entries = [
        ScheduleEntry(
            match_id=row[0],
            stage_id=row[1],
            kickoff_time=_berlin(row[2]),
            status=row[3],
            fixture_synced_at=_berlin(row[4]),
            prematch_synced_at=_berlin(row[5]),
            lineups_confirmed_at=_berlin(row[6]),
            details_synced_at=_berlin(row[7]),
            details_final_at=_berlin(row[8]),
            last_attempt_at=_berlin(row[9]),
            attempts=row[10] or 0,
        )
        for row in rows
        if row[2] is not None
    ]
    global _cache, _cache_loaded
    with _cache_lock:
        _cache = entries
        _cache_loaded = True
    logger.debug("Spielplan-Cache aktualisiert: %d Spiele", len(entries))
    return len(entries)


def get_schedule_cache() -> list[ScheduleEntry]:
    with _cache_lock:
        return list(_cache)


def schedule_cache_loaded() -> bool:
    with _cache_lock:
        return _cache_loaded


def reset_schedule_cache() -> None:
    global _cache, _cache_loaded
    with _cache_lock:
        _cache = []
        _cache_loaded = False


def _load_cache(session_factory: SessionFactory, now: datetime) -> None:
    db = session_factory()
    try:
        refresh_schedule_cache(db, now)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Gemeinsamer Lauf-Rahmen
# ---------------------------------------------------------------------------

def _execute(
    name: str,
    session_factory: SessionFactory,
    client_factory: ClientFactory,
    lock_timeout: float,
    work: Callable[[Any, Any], dict],
    now: datetime,
) -> dict:
    """Öffnet DB-Session + Advisory-Lock + EINEN Client, führt ``work`` aus, aktualisiert danach den Cache."""
    started = time.monotonic()
    db = session_factory()
    try:
        with scraper_db_lock(db) as acquired:
            if not acquired:
                logger.info("%s: anderer Prozess scrapt gerade (Advisory-Lock) – übersprungen", name)
                return {"status": "locked"}
            summary: dict
            pages = 0
            try:
                with client_factory(lock_timeout=lock_timeout) as client:
                    try:
                        summary = work(db, client)
                    finally:
                        pages = int(getattr(client, "pages_loaded", 0) or 0)
            except BrowserBusyError as exc:
                logger.info("%s: Browser belegt – übersprungen (%s)", name, exc)
                return {"status": "busy"}
            except Exception as exc:  # noqa: BLE001 – ein Lauf darf den Scheduler nie beenden
                logger.exception("%s: Lauf fehlgeschlagen: %s", name, exc)
                db.rollback()
                summary = {"status": "error", "error": str(exc)}
            try:
                refresh_schedule_cache(db, now)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s: Cache-Aktualisierung fehlgeschlagen: %s", name, exc)
            summary.setdefault("status", "ok")
            summary["pages_loaded"] = pages
            summary["duration_s"] = round(time.monotonic() - started, 1)
            logger.info("%s fertig: %s", name, summary)
            return summary
    finally:
        db.close()


def _fetch_details(
    db: Any,
    client: Any,
    match_ids: list[int],
    now: datetime,
    *,
    max_attempts: int,
    gap: timedelta,
    limit: int | None = None,
) -> dict:
    """Ruft für beendete Spiele ohne Details das Match Centre ab (je Spiel isoliert)."""
    result = {"ok": 0, "unavailable": 0, "error": 0}
    done = 0
    for match_id in match_ids:
        if limit is not None and done >= limit:
            break
        match = db.get(Match, match_id)
        if match is None or match.status != "finished":
            continue
        state = db.get(MatchSyncState, match_id)
        if state is not None:
            if state.details_synced_at is not None or (state.attempts or 0) >= max_attempts:
                continue
            last = _berlin(state.last_attempt_at)
            if last is not None and now - last < gap:
                continue
        done += 1
        try:
            status = fs.sync_match_details(db, client, match).get("status", "error")
        except BrowserBusyError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Details für Match %s fehlgeschlagen", match_id)
            db.rollback()
            status = "error"
        result[status if status in result else "error"] += 1
    return result


def _refresh_groups(db: Any, client: Any, groups: dict[tuple[int, int, int], list[ScheduleEntry]]) -> int:
    """Aktualisiert je (Stage, Monat) genau einmal die Fixtures (1 Seite); liefert die Zahl erfolgreicher Gruppen."""
    refreshed = 0
    for (stage_id, year, month) in groups:
        try:
            stage = db.get(Stage, stage_id)
            if stage is None:
                continue
            fs.sync_stage_month(db, client, stage, year, month)
            refreshed += 1
        except BrowserBusyError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Fixture-Refresh Stage %s %04d-%02d fehlgeschlagen: %s", stage_id, year, month, exc)
            db.rollback()
    return refreshed


# ---------------------------------------------------------------------------
# Matchday-Tick
# ---------------------------------------------------------------------------

@dataclass
class TickPlan:
    prematch: list[ScheduleEntry] = field(default_factory=list)
    lineup_retry: list[ScheduleEntry] = field(default_factory=list)
    poll_groups: dict[tuple[int, int, int], list[ScheduleEntry]] = field(default_factory=dict)
    detail_due: list[ScheduleEntry] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not (self.prematch or self.lineup_retry or self.poll_groups or self.detail_due)


def _prematch_done(entry: ScheduleEntry) -> bool:
    """Prematch gilt als erledigt, wenn Preview- ODER Fixture-Sync nach T-45 min stattfand.

    ``prematch_synced_at`` wird nur bei vorhandener Vorschau gesetzt; ``fixture_synced_at`` (vom
    Fixture-Refresh in ``sync_prematch``) deckt Spiele ohne Preview ab.
    """
    threshold = entry.kickoff_time - PREMATCH_LEAD
    return any(ts is not None and ts >= threshold for ts in (entry.prematch_synced_at, entry.fixture_synced_at))


def _details_retry_due(entry: ScheduleEntry, now: datetime, max_attempts: int, gap: timedelta) -> bool:
    if entry.status != "finished" or entry.details_synced_at is not None or entry.attempts >= max_attempts:
        return False
    return entry.last_attempt_at is None or now - entry.last_attempt_at >= gap


def plan_tick(entries: list[ScheduleEntry], now: datetime) -> TickPlan:
    """Entscheidet rein aus dem Cache, was im Tick fällig ist."""
    plan = TickPlan()
    for entry in entries:
        kickoff = entry.kickoff_time
        until = kickoff - now
        if timedelta(0) < until <= PREMATCH_LEAD and entry.status == "scheduled":
            if not _prematch_done(entry):
                plan.prematch.append(entry)
            elif entry.lineups_confirmed_at is None and until <= LINEUP_RETRY_LEAD:
                attempts = [ts for ts in (entry.details_synced_at, entry.last_attempt_at) if ts is not None]
                last = max(attempts) if attempts else None
                if last is None or last < kickoff - LINEUP_RETRY_MIN_AGE:
                    plan.lineup_retry.append(entry)
            continue

        since = now - kickoff
        if entry.status in ("scheduled", "live") and POSTMATCH_START <= since <= POSTMATCH_END:
            gap = POLL_GAP_FAST if since < POSTMATCH_FAST_UNTIL else POLL_GAP_SLOW
            if entry.fixture_synced_at is None or now - entry.fixture_synced_at >= gap:
                plan.poll_groups.setdefault(entry.month_key, []).append(entry)
        elif timedelta(0) < since <= POSTMATCH_END and _details_retry_due(
            entry, now, TICK_MAX_ATTEMPTS, DETAIL_RETRY_GAP
        ):
            plan.detail_due.append(entry)
    return plan


def _tick_work(db: Any, client: Any, plan: TickPlan, now: datetime) -> dict:
    summary = {"prematch": 0, "lineup_retry": 0, "polled_groups": 0, "details_ok": 0, "details_failed": 0}

    # Prematch: je (Stage, Monat) EINE Fixture-Seite, danach pro Spiel nur Preview + Match Centre
    prematch_groups: dict[tuple[int, int, int], list[ScheduleEntry]] = {}
    for entry in plan.prematch:
        prematch_groups.setdefault(entry.month_key, []).append(entry)
    for (stage_id, year, month), entries in prematch_groups.items():
        try:
            stage = db.get(Stage, stage_id)
            if stage is None:
                continue
            previews = fs.sync_stage_month(db, client, stage, year, month).get("has_preview", {})
        except BrowserBusyError:
            raise
        except Exception as exc:  # noqa: BLE001 – Gruppe im nächsten Tick erneut versuchen
            logger.warning("Prematch-Fixture-Refresh Stage %s %04d-%02d fehlgeschlagen: %s", stage_id, year, month, exc)
            db.rollback()
            continue
        for entry in sorted(entries, key=lambda e: e.kickoff_time):
            try:
                match = db.get(Match, entry.match_id)
                if match is not None:
                    fs.sync_prematch(
                        db,
                        client,
                        match,
                        refresh_fixtures=False,
                        has_preview=previews.get(match.ws_match_id, False),
                    )
                    summary["prematch"] += 1
            except BrowserBusyError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Prematch für Match %s fehlgeschlagen", entry.match_id)
                db.rollback()

    for entry in sorted(plan.lineup_retry, key=lambda e: e.kickoff_time):
        try:
            match = db.get(Match, entry.match_id)
            if match is not None:
                fs.sync_match_details(db, client, match)
                summary["lineup_retry"] += 1
        except BrowserBusyError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Aufstellungs-Retry für Match %s fehlgeschlagen", entry.match_id)
            db.rollback()

    detail_ids = [e.match_id for e in plan.detail_due]
    if plan.poll_groups:
        summary["polled_groups"] = _refresh_groups(db, client, plan.poll_groups)
        detail_ids.extend(e.match_id for entries in plan.poll_groups.values() for e in entries)

    if detail_ids:
        done = _fetch_details(
            db, client, sorted(set(detail_ids)), now, max_attempts=TICK_MAX_ATTEMPTS, gap=DETAIL_RETRY_GAP
        )
        summary["details_ok"] = done["ok"]
        summary["details_failed"] = done["unavailable"] + done["error"]
    return summary


def run_matchday_tick(
    now: datetime | None = None,
    client_factory: ClientFactory = WhoScoredClient,
    session_factory: SessionFactory | None = None,
) -> dict:
    """Alle 3 Minuten: Prematch, Aufstellungs-Retry, Post-Match-Polling. Idle = 0 DB-Abfragen, kein Client."""
    now = _now(now)
    session_factory = session_factory or _default_session_factory
    if not schedule_cache_loaded():
        try:
            _load_cache(session_factory, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("football_matchday_tick: Spielplan-Cache nicht ladbar: %s", exc)
            return {"status": "cache_error"}

    plan = plan_tick(get_schedule_cache(), now)
    if plan.empty:
        return {"status": "idle"}
    return _execute(
        "football_matchday_tick",
        session_factory,
        client_factory,
        TICK_LOCK_TIMEOUT,
        lambda db, client: _tick_work(db, client, plan, now),
        now,
    )


# ---------------------------------------------------------------------------
# Stündlicher Catch-up
# ---------------------------------------------------------------------------

@dataclass
class CatchupPlan:
    details: list[ScheduleEntry] = field(default_factory=list)
    stale_groups: dict[tuple[int, int, int], list[ScheduleEntry]] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not (self.details or self.stale_groups)


def plan_catchup(entries: list[ScheduleEntry], now: datetime) -> CatchupPlan:
    plan = CatchupPlan()
    for entry in sorted(entries, key=lambda e: e.kickoff_time):
        if entry.kickoff_time < now - CATCHUP_LOOKBACK:
            continue
        if entry.status == "finished":
            if _details_retry_due(entry, now, CATCHUP_MAX_ATTEMPTS, CATCHUP_RETRY_GAP):
                plan.details.append(entry)
        elif entry.status in ("scheduled", "live"):
            deadline = entry.kickoff_time + POSTMATCH_END
            if deadline < now and (entry.fixture_synced_at is None or entry.fixture_synced_at < deadline):
                plan.stale_groups.setdefault(entry.month_key, []).append(entry)
    return plan


def _catchup_work(db: Any, client: Any, plan: CatchupPlan, now: datetime) -> dict:
    summary = {"refreshed_groups": 0, "details_ok": 0, "details_failed": 0}
    ids = [e.match_id for e in plan.details]
    if plan.stale_groups:
        summary["refreshed_groups"] = _refresh_groups(db, client, plan.stale_groups)
        # Status-Korrektur kann Spiele auf "finished" setzen -> deren Details gleich mitladen
        ids.extend(e.match_id for entries in plan.stale_groups.values() for e in entries)
    if ids:
        kickoffs = {
            row[0]: _berlin(row[1])
            for row in db.execute(select(Match.id, Match.kickoff_time).where(Match.id.in_(ids)))
        }
        ordered = sorted(set(ids), key=lambda i: kickoffs.get(i) or now)
        done = _fetch_details(
            db, client, ordered, now, max_attempts=CATCHUP_MAX_ATTEMPTS, gap=CATCHUP_RETRY_GAP, limit=CATCHUP_LIMIT
        )
        summary["details_ok"] = done["ok"]
        summary["details_failed"] = done["unavailable"] + done["error"]
    return summary


def run_hourly_catchup(
    now: datetime | None = None,
    client_factory: ClientFactory = WhoScoredClient,
    session_factory: SessionFactory | None = None,
) -> dict:
    """Stündlich: fehlende Details (attempts < 8, max. 25, älteste zuerst) + Status-Korrektur überfälliger Spiele.

    Spiele ohne Match Centre (z. B. DFB-Pokal) werden nach 8 Versuchen nicht mehr abgerufen.
    """
    now = _now(now)
    session_factory = session_factory or _default_session_factory
    if not schedule_cache_loaded():
        try:
            _load_cache(session_factory, now)
        except Exception as exc:  # noqa: BLE001
            logger.warning("football_hourly_catchup: Spielplan-Cache nicht ladbar: %s", exc)
            return {"status": "cache_error"}

    plan = plan_catchup(get_schedule_cache(), now)
    if plan.empty:
        return {"status": "idle"}
    return _execute(
        "football_hourly_catchup",
        session_factory,
        client_factory,
        LONG_LOCK_TIMEOUT,
        lambda db, client: _catchup_work(db, client, plan, now),
        now,
    )


# ---------------------------------------------------------------------------
# Daily-Sync / Bootstrap
# ---------------------------------------------------------------------------

def incremental_months(now: datetime) -> list[tuple[int, int]]:
    """Vormonat (nur bis einschließlich 7. des Monats), aktueller und nächster Monat."""

    def shift(year: int, month: int, delta: int) -> tuple[int, int]:
        index = year * 12 + (month - 1) + delta
        return index // 12, index % 12 + 1

    months = []
    if now.day <= 7:
        months.append(shift(now.year, now.month, -1))
    months.append((now.year, now.month))
    months.append(shift(now.year, now.month, 1))
    return months


def _season_match_count(db: Any, season: Season) -> int:
    """0 oder 1 – es genügt zu wissen, ob die Saison überhaupt Spiele hat."""
    return len(db.scalars(select(Match.id).join(Stage, Stage.id == Match.stage_id).where(Stage.season_id == season.id).limit(1)).all())


def _league_needs_bootstrap(db: Any, league_key: str, season_code: str) -> bool:
    """True, wenn die Saison fehlt oder noch kein Spiel enthält (reine DB-Abfrage)."""
    season = db.scalars(
        select(Season)
        .join(Competition, Competition.id == Season.competition_id)
        .where(Competition.league_key == league_key, Season.code == season_code)
    ).first()
    return season is None or _season_match_count(db, season) == 0


def _daily_work(db: Any, client: Any, now: datetime, league_keys: set[str] | None = None) -> dict:
    """Spielpläne synchronisieren; ``league_keys`` gesetzt = Bootstrap (nur diese, komplett, kein Nachladen)."""
    summary = {"competitions": 0, "full": 0, "incremental": 0, "errors": 0, "finals": 0}
    for config in enabled_competitions():
        if league_keys is not None and config.league_key not in league_keys:
            continue
        try:
            code = current_season_code(now, config.season_start_month)
            season = fs.ensure_season(db, client, config.league_key, code)
            if league_keys is not None or now.weekday() == 0 or _season_match_count(db, season) == 0:
                # Bootstrap (leere Saison) bzw. wöchentlicher Voll-Refresh (montags) gegen Terminverschiebungen
                fs.sync_fixtures(db, client, season, months=None)
                summary["full"] += 1
            else:
                fs.sync_fixtures(db, client, season, months=incremental_months(now))
                summary["incremental"] += 1
            summary["competitions"] += 1
        except BrowserBusyError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Daily-Sync %s fehlgeschlagen: %s", config.league_key, exc)
            db.rollback()
            summary["errors"] += 1

    if league_keys is None:
        # Finaler Nachlade-Lauf: Details einmal nach >= 6 h erneut laden (Upsert, nur ergänzend)
        rows = db.execute(
            select(Match.id)
            .join(MatchSyncState, MatchSyncState.match_id == Match.id)
            .where(
                Match.status == "finished",
                Match.kickoff_time >= now - CATCHUP_LOOKBACK,
                Match.kickoff_time <= now - FINAL_RELOAD_AFTER,
                MatchSyncState.details_synced_at.is_not(None),
                MatchSyncState.details_final_at.is_(None),
            )
            .order_by(Match.kickoff_time)
        ).all()
        for (match_id,) in rows:
            try:
                match = db.get(Match, match_id)
                if match is not None and fs.sync_match_details(db, client, match, final=True).get("status") == "ok":
                    summary["finals"] += 1
            except BrowserBusyError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("Finaler Detail-Abruf für Match %s fehlgeschlagen", match_id)
                db.rollback()
    return summary


def run_daily_sync(
    now: datetime | None = None,
    client_factory: ClientFactory = WhoScoredClient,
    session_factory: SessionFactory | None = None,
) -> dict:
    """Täglich 04:00: Spielpläne (inkrementell, montags/Bootstrap komplett) + finaler Detail-Nachlauf."""
    now = _now(now)
    session_factory = session_factory or _default_session_factory
    return _execute(
        "football_daily_sync",
        session_factory,
        client_factory,
        LONG_LOCK_TIMEOUT,
        lambda db, client: _daily_work(db, client, now),
        now,
    )


def run_bootstrap(
    now: datetime | None = None,
    client_factory: ClientFactory = WhoScoredClient,
    session_factory: SessionFactory | None = None,
) -> dict:
    """Einmalig nach dem Start: füllt nur Wettbewerbe, deren aktuelle Saison noch keine Spiele hat.

    Lädt immer auch den Spielplan-Cache (die DB wird beim Start ohnehin geweckt).
    """
    now = _now(now)
    session_factory = session_factory or _default_session_factory
    db = session_factory()
    try:
        refresh_schedule_cache(db, now)
        needed = {
            config.league_key
            for config in enabled_competitions()
            if _league_needs_bootstrap(db, config.league_key, current_season_code(now, config.season_start_month))
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("football_bootstrap: DB-Prüfung fehlgeschlagen: %s", exc)
        return {"status": "error", "error": str(exc)}
    finally:
        db.close()

    if not needed:
        logger.info("football_bootstrap: alle aktuellen Saisons enthalten bereits Spiele")
        return {"status": "idle"}
    logger.info("football_bootstrap: Erst-Import für %s", ", ".join(sorted(needed)))
    return _execute(
        "football_bootstrap",
        session_factory,
        client_factory,
        LONG_LOCK_TIMEOUT,
        lambda db, client: _daily_work(db, client, now, league_keys=needed),
        now,
    )


# ---------------------------------------------------------------------------
# Scheduler-Registrierung
# ---------------------------------------------------------------------------

def job_daily_sync() -> None:
    run_daily_sync()


def job_matchday_tick() -> None:
    run_matchday_tick()


def job_hourly_catchup() -> None:
    run_hourly_catchup()


def job_bootstrap() -> None:
    run_bootstrap()


def register_jobs(scheduler: Any) -> None:
    """Registriert die Fußball-Jobs (nur aufrufen, wenn ``settings.whoscored_enabled``)."""
    common = {"max_instances": 1, "coalesce": True, "replace_existing": True}
    scheduler.add_job(
        job_daily_sync, trigger="cron", hour=4, minute=0, id="football_daily_sync", misfire_grace_time=3600, **common
    )
    scheduler.add_job(
        job_matchday_tick, trigger="interval", minutes=3, id="football_matchday_tick", misfire_grace_time=120, **common
    )
    scheduler.add_job(
        job_hourly_catchup, trigger="cron", minute=17, id="football_hourly_catchup", misfire_grace_time=1800, **common
    )
    scheduler.add_job(
        job_bootstrap,
        trigger="date",
        run_date=datetime.now(scheduler.timezone) + timedelta(seconds=60),
        id="football_bootstrap",
        misfire_grace_time=600,
        **common,
    )
    logger.info(
        "Fußball-Jobs registriert: football_daily_sync (04:00), football_matchday_tick (alle 3 min), "
        "football_hourly_catchup (:17), football_bootstrap (einmalig +60 s)"
    )
