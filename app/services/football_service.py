"""Schreibende Seite der WhoScored-Fußballintegration (idempotente Importe/Upserts).

Alle Funktionen mit ``client`` erwarten einen bereits geöffneten ``WhoScoredClient`` – der Aufrufer
steuert die (einzige) Browser-Session. Jede Funktion committet selbst.

Wichtige Regeln:

* Re-Syncs fügen nur HINZU oder AKTUALISIEREN, es werden nie Zeilen gelöscht – einzige Ausnahme:
  ``sync_missing_players`` (aktuelle Ausfälle ersetzen die alten, damit die Tabelle klein bleibt).
* Der Fixture-Feed überschreibt nie einen vorhandenen Wert (Tore, Zeitstempel) mit ``None``.
* Match-Details werden pro Spiel in EINER Transaktion geschrieben; bei Fehlern wird nur dieses
  Spiel zurückgerollt. Die Daten eines Spiels werden vorab in wenigen Abfragen geladen und im
  Speicher verglichen (Remote-DB mit hoher Latenz).
* Eigentore: ``MatchIncident.team_id`` ist das Team des Schützen (WhoScored-Semantik); das Tor
  zählt für den Gegner.
* Zeitstempel in Berliner Zeit.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import insert, or_, select
from sqlalchemy.orm import Session

from app.models import (
    Appearance,
    Competition,
    Country,
    Formation,
    FormationPosition,
    Manager,
    Match,
    MatchIncident,
    MatchSyncState,
    MatchTeam,
    MissingPlayer,
    Player,
    PlayerMatchStat,
    Referee,
    Region,
    Season,
    Stage,
    StatType,
    Team,
    TeamMatchStat,
    Venue,
)
from app.services.datasources.whoscored import WhoScoredClient, WhoScoredError, normalize_season_code
from app.services.football_competitions import get_competition_config

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")
_EPS = 1e-9


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(BERLIN_TZ)


def _to_berlin(value: datetime | None) -> datetime | None:
    """Vereinheitlicht Zeitstempel (SQLite liefert naive Werte = Berliner Wandzeit)."""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=BERLIN_TZ)
    return value.astimezone(BERLIN_TZ)


def _same_dt(a: datetime | None, b: datetime | None) -> bool:
    a, b = _to_berlin(a), _to_berlin(b)
    if a is None or b is None:
        return a is b
    return a == b


def _set_attr(obj: Any, attr: str, value: Any, *, allow_none: bool = False) -> bool:
    """Setzt ``obj.attr`` nur bei echter Änderung; ``None`` überschreibt standardmäßig nichts."""
    if value is None and not allow_none:
        return False
    if getattr(obj, attr) == value:
        return False
    setattr(obj, attr, value)
    return True


def _set_dt(obj: Any, attr: str, value: datetime | None) -> bool:
    if value is None or _same_dt(getattr(obj, attr), value):
        return False
    setattr(obj, attr, value)
    return True


def _set_float(obj: Any, attr: str, value: float | None) -> bool:
    if value is None:
        return False
    current = getattr(obj, attr)
    if current is not None and abs(current - value) <= _EPS:
        return False
    setattr(obj, attr, value)
    return True


def _pages(client: Any) -> int:
    return int(getattr(client, "pages_loaded", 0) or 0)


def _get_or_create_state(db: Session, match_id: int) -> MatchSyncState:
    state = db.get(MatchSyncState, match_id)
    if state is None:
        state = MatchSyncState(match_id=match_id, attempts=0)
        db.add(state)
    return state


def get_or_create_sync_state(db: Session, match: Match) -> MatchSyncState:
    """Liefert den Sync-Stand des Spiels (legt ihn an, falls er fehlt; kein Commit)."""
    return _get_or_create_state(db, match.id)


def _bulk_insert(db: Session, model: Any, rows: list[dict]) -> None:
    """Fügt Zeilen per Core-Bulk-Insert ein (ein Statement, unabhängig vom DB-Dialekt)."""
    if rows:
        db.execute(insert(model.__table__), rows)


def _bulk_returning(db: Session, model: Any, rows: list[dict], columns: tuple[str, ...]) -> list[Any]:
    """Bulk-Insert mit RETURNING (ein Statement); Zuordnung über natürliche Schlüssel, nicht über die Reihenfolge."""
    if not rows:
        return []
    table = model.__table__
    return list(db.execute(insert(table).returning(*[table.c[c] for c in columns]), rows).all())


def _bulk_insert_ids(db: Session, model: Any, rows: list[dict], key_column: str) -> dict[Any, int]:
    """Bulk-Insert; liefert ``{natürlicher Schlüssel: neue id}``."""
    return {r._mapping[key_column]: r._mapping["id"] for r in _bulk_returning(db, model, rows, ("id", key_column))}


# ---------------------------------------------------------------------------
# Saison / Stages
# ---------------------------------------------------------------------------

def ensure_season(db: Session, client: WhoScoredClient, league_key: str, season_code: str, refresh: bool = False) -> Season:
    """Stellt Region, Wettbewerb, Saison und Stages in der DB sicher.

    Existiert die Saison bereits (mit mindestens einer Stage) und ``refresh`` ist False, wird sie
    OHNE Seitenabruf zurückgegeben. Sonst werden die Metadaten (3 Seiten) geladen und upserted.
    """
    config = get_competition_config(league_key)
    code = normalize_season_code(season_code)

    if not refresh:
        existing = db.scalars(
            select(Season)
            .join(Competition, Competition.id == Season.competition_id)
            .where(Competition.league_key == league_key, Season.code == code)
        ).first()
        if existing is not None:
            has_stage = db.scalars(select(Stage.id).where(Stage.season_id == existing.id).limit(1)).first()
            if has_stage is not None:
                return existing

    meta = client.fetch_season_metadata(
        code,
        ws_region_id=config.ws_region_id,
        ws_tournament_id=config.ws_tournament_id,
    )

    region = db.scalars(select(Region).where(Region.ws_region_id == config.ws_region_id)).first()
    if region is None:
        region = Region(ws_region_id=config.ws_region_id, name=config.region_name)
        db.add(region)
    else:
        _set_attr(region, "name", config.region_name)

    competition = db.scalars(
        select(Competition).where(Competition.ws_tournament_id == config.ws_tournament_id)
    ).first()
    if competition is None:
        competition = db.scalars(select(Competition).where(Competition.league_key == league_key)).first()
    if competition is None:
        competition = Competition(
            ws_tournament_id=config.ws_tournament_id,
            region=region,
            league_key=league_key,
            name=config.name,
            slug=config.slug,
            format=config.format,
        )
        db.add(competition)
    else:
        competition.region = region
        _set_attr(competition, "ws_tournament_id", config.ws_tournament_id)
        _set_attr(competition, "league_key", league_key)
        _set_attr(competition, "name", config.name)
        _set_attr(competition, "slug", config.slug)
        _set_attr(competition, "format", config.format)
    db.flush()

    season_meta = meta["season"]
    season = db.scalars(select(Season).where(Season.ws_season_id == season_meta["ws_season_id"])).first()
    if season is None:
        season = db.scalars(
            select(Season).where(Season.competition_id == competition.id, Season.code == code)
        ).first()
    if season is None:
        season = Season(competition_id=competition.id, ws_season_id=season_meta["ws_season_id"], code=code)
        db.add(season)
    else:
        _set_attr(season, "competition_id", competition.id)
        _set_attr(season, "ws_season_id", season_meta["ws_season_id"])
        _set_attr(season, "code", code)
    db.flush()

    stage_ids = [s["ws_stage_id"] for s in meta["stages"]]
    stages = {
        s.ws_stage_id: s for s in db.scalars(select(Stage).where(Stage.ws_stage_id.in_(stage_ids)))
    }
    for stage_meta in meta["stages"]:
        stage = stages.get(stage_meta["ws_stage_id"])
        if stage is None:
            db.add(
                Stage(
                    season_id=season.id,
                    ws_stage_id=stage_meta["ws_stage_id"],
                    name=stage_meta.get("name"),
                    is_default=bool(stage_meta.get("is_default")),
                )
            )
        else:
            _set_attr(stage, "season_id", season.id)
            _set_attr(stage, "name", stage_meta.get("name"))
            _set_attr(stage, "is_default", bool(stage_meta.get("is_default")))

    db.commit()
    logger.info("Saison %s %s sichergestellt (%d Stages)", league_key, code, len(stage_ids))
    return season


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_FIXTURE_FIELDS_NONE_SAFE = (
    "home_score",
    "away_score",
    "et_home_score",
    "et_away_score",
    "pen_home_score",
    "pen_away_score",
)
_FIXTURE_DT_FIELDS = ("kickoff_time", "started_at", "first_half_ended_at", "second_half_started_at")


class _FixtureContext:
    """Zwischenspeicher für einen ``sync_fixtures``-Lauf (Länder, Stages als reine IDs)."""

    def __init__(self, db: Session, season_id: int):
        self.countries_by_name: dict[str, Country] = {}
        self.country_codes: set[str] = set()
        # (id, ws_stage_id), Standard-Stage zuerst
        self.stages: list[tuple[int, int]] = [
            (row.id, row.ws_stage_id)
            for row in db.execute(
                select(Stage.id, Stage.ws_stage_id)
                .where(Stage.season_id == season_id)
                .order_by(Stage.is_default.desc(), Stage.id)
            )
        ]
        self.stage_id_by_ws_id = {ws_id: stage_id for stage_id, ws_id in self.stages}

    def reload_countries(self, db: Session) -> None:
        """Lädt die Länder neu (nach jedem Commit sind die ORM-Objekte abgelaufen)."""
        self.countries_by_name.clear()
        self.country_codes.clear()
        for country in db.scalars(select(Country)):
            self.countries_by_name[country.name] = country
            if country.code:
                self.country_codes.add(country.code)

    def country(self, db: Session, name: str | None, code: str | None) -> Country | None:
        if not name:
            return None
        country = self.countries_by_name.get(name)
        if country is None:
            country = Country(name=name, code=code if code and code not in self.country_codes else None)
            if country.code:
                self.country_codes.add(country.code)
            db.add(country)
            self.countries_by_name[name] = country
        elif code and not country.code and code not in self.country_codes:
            country.code = code
            self.country_codes.add(code)
        return country


def _apply_fixtures(
    db: Session,
    ctx: _FixtureContext,
    fallback_stage_id: int,
    fixtures: list[dict],
    counters: dict,
    now: datetime,
) -> None:
    """Schreibt die Fixtures eines Monats (Upsert) und committet."""
    if not fixtures:
        return

    ctx.reload_countries(db)
    ws_team_ids = {f[side]["ws_team_id"] for f in fixtures for side in ("home", "away")}
    teams = {t.ws_team_id: t for t in db.scalars(select(Team).where(Team.ws_team_id.in_(ws_team_ids)))}
    matches = {
        m.ws_match_id: m
        for m in db.scalars(select(Match).where(Match.ws_match_id.in_([f["ws_match_id"] for f in fixtures])))
    }

    team_countries: dict[int, Country | None] = {}
    for fixture in fixtures:
        for side in ("home", "away"):
            data = fixture[side]
            team_countries[data["ws_team_id"]] = ctx.country(
                db, data.get("country_name"), data.get("country_code")
            )
    db.flush()  # neue Länder -> IDs

    for fixture in fixtures:
        for side in ("home", "away"):
            data = fixture[side]
            country = team_countries[data["ws_team_id"]]
            team = teams.get(data["ws_team_id"])
            if team is None:
                team = Team(
                    ws_team_id=data["ws_team_id"],
                    name=data["name"] or f"Team {data['ws_team_id']}",
                    country_id=country.id if country else None,
                )
                db.add(team)
                teams[data["ws_team_id"]] = team
            else:
                if data["name"]:
                    _set_attr(team, "name", data["name"])
                if country is not None:
                    _set_attr(team, "country_id", country.id)
    db.flush()

    new_matches: list[tuple[Match, dict]] = []
    touched: list[Match] = []
    for fixture in fixtures:
        stage_id = ctx.stage_id_by_ws_id.get(fixture.get("ws_stage_id")) or fallback_stage_id
        match = matches.get(fixture["ws_match_id"])
        if match is None:
            match = Match(
                ws_match_id=fixture["ws_match_id"],
                stage_id=stage_id,
                home_team_id=teams[fixture["home"]["ws_team_id"]].id,
                away_team_id=teams[fixture["away"]["ws_team_id"]].id,
                kickoff_time=fixture["kickoff_time"],
                status=fixture["status"],
                **{f: fixture[f] for f in _FIXTURE_FIELDS_NONE_SAFE},
                **{f: fixture[f] for f in _FIXTURE_DT_FIELDS if f != "kickoff_time"},
            )
            db.add(match)
            matches[fixture["ws_match_id"]] = match
            new_matches.append((match, fixture))
            counters["created"] += 1
            continue

        touched.append(match)
        changed = False
        old_status = match.status
        changed |= _set_attr(match, "stage_id", stage_id)
        changed |= _set_attr(match, "status", fixture["status"])
        for field in _FIXTURE_FIELDS_NONE_SAFE:
            changed |= _set_attr(match, field, fixture[field])
        for field in _FIXTURE_DT_FIELDS:
            changed |= _set_dt(match, field, fixture[field])
        if changed:
            counters["updated"] += 1
            if old_status != "finished" and fixture["status"] == "finished":
                counters["newly_finished"].append(match.id)
        else:
            counters["unchanged"] += 1

    db.flush()

    state_ids = [m.id for m in touched]
    states = {s.match_id: s for s in db.scalars(select(MatchSyncState).where(MatchSyncState.match_id.in_(state_ids)))} if state_ids else {}
    for match in touched:
        state = states.get(match.id)
        if state is None:
            db.add(MatchSyncState(match_id=match.id, attempts=0, fixture_synced_at=now))
        else:
            state.fixture_synced_at = now
    for match, _fixture in new_matches:
        db.add(MatchSyncState(match_id=match.id, attempts=0, fixture_synced_at=now))
    db.commit()


def _sync_fixtures(
    db: Session,
    client: Any,
    season: Season,
    months: list[tuple[int, int]] | None,
    stage_ws_ids: set[int] | None = None,
) -> tuple[dict, dict[int, dict]]:
    """Kern von ``sync_fixtures``; liefert zusätzlich ``{ws_match_id: fixture}`` der geladenen Spiele."""
    season_id = season.id
    ws_season_id = season.ws_season_id
    competition = db.get(Competition, season.competition_id)
    region = db.get(Region, competition.region_id)
    ws_region_id, ws_tournament_id = region.ws_region_id, competition.ws_tournament_id

    ctx = _FixtureContext(db, season_id)
    stages = [(sid, ws_id) for sid, ws_id in ctx.stages if stage_ws_ids is None or ws_id in stage_ws_ids]
    counters: dict = {"created": 0, "updated": 0, "unchanged": 0, "newly_finished": []}
    seen: dict[int, dict] = {}
    pages_before = _pages(client)
    now = _now()

    for stage_id, stage_ws_id in stages:
        stage_months = months
        if stage_months is None:
            stage_months = client.fetch_calendar_months(ws_region_id, ws_tournament_id, ws_season_id, stage_ws_id)
        for year, month in stage_months:
            fixtures = client.fetch_fixtures_month(stage_ws_id, year, month)
            _apply_fixtures(db, ctx, stage_id, fixtures, counters, now)
            for fixture in fixtures:
                seen[fixture["ws_match_id"]] = fixture
            logger.info(
                "Fixtures Stage %s %04d-%02d: %d Spiele", stage_ws_id, year, month, len(fixtures)
            )

    counters["pages"] = _pages(client) - pages_before
    return counters, seen


def sync_fixtures(db: Session, client: WhoScoredClient, season: Season, months: list[tuple[int, int]] | None = None) -> dict:
    """Synchronisiert die Spielpläne einer Saison (Upsert, commit je Monat).

    ``months=None`` lädt den kompletten Saisonkalender; sonst nur die angegebenen ``(jahr, monat)``.

    Rückgabe: ``{"created", "updated", "unchanged", "newly_finished": [match.id, ...], "pages"}``.
    ``newly_finished`` enthält nur bereits bekannte Spiele, deren Status in diesem Aufruf auf
    ``finished`` wechselte.
    """
    summary, _seen = _sync_fixtures(db, client, season, months)
    return summary


def sync_stage_month(db: Session, client: WhoScoredClient, stage: Stage, year: int, month: int) -> dict:
    """Aktualisiert genau EINEN Monat einer Stage (1 Seitenabruf), z. B. für das Polling nach Spielende.

    Rückgabe wie bei ``sync_fixtures`` (``created``/``updated``/``unchanged``/``newly_finished``/``pages``).
    """
    season = db.get(Season, stage.season_id)
    summary, seen = _sync_fixtures(db, client, season, [(year, month)], {stage.ws_stage_id})
    # ``has_preview``: {ws_match_id: bool} der geladenen Spiele (für ``sync_prematch(refresh_fixtures=False)``)
    summary["has_preview"] = {ws_id: bool(f.get("has_preview")) for ws_id, f in seen.items()}
    return summary


# ---------------------------------------------------------------------------
# Match-Details
# ---------------------------------------------------------------------------

def _is_upcoming(status: str | None, kickoff: datetime | None, now: datetime) -> bool:
    """Spiel ist noch nicht angepfiffen (Status ``scheduled`` und Anpfiff in der Zukunft)."""
    kickoff = _to_berlin(kickoff)
    return status == "scheduled" and kickoff is not None and kickoff > now


def _record_attempt(db: Session, match_id: int, error: str | None, unavailable: bool = False) -> None:
    """Speichert einen (fehlgeschlagenen/leeren) Abrufversuch im Sync-Stand.

    ``last_attempt_at`` wird immer gesetzt. ``attempts`` zählt nur Versuche NACH dem Anpfiff; bei
    noch nicht angepfiffenen Spielen werden ``attempts`` und der „nicht verfügbar“-Fehler (``unavailable``)
    nicht verändert (Vorab-Versuche verbrauchen nicht das Nachlade-Budget).
    """
    state = _get_or_create_state(db, match_id)
    now = _now()
    state.last_attempt_at = now
    match = db.get(Match, match_id)
    upcoming = match is not None and _is_upcoming(match.status, match.kickoff_time, now)
    if not upcoming:
        state.attempts = (state.attempts or 0) + 1
    if not (upcoming and unavailable):
        state.last_error = error
    db.commit()


def _store_match_details(db: Session, match: Match, centre: dict, final: bool, now: datetime) -> dict:
    """Schreibt das Match Centre eines Spiels (ohne Commit)."""
    match_id = match.id
    home_team_id, away_team_id = match.home_team_id, match.away_team_id

    # -- Vorab laden (wenige Abfragen) --------------------------------------
    state = _get_or_create_state(db, match_id)
    teams = {
        t.ws_team_id: t for t in db.scalars(select(Team).where(Team.id.in_([home_team_id, away_team_id])))
    }
    blocks = (centre["home"], centre["away"])
    for block in blocks:
        if block["ws_team_id"] not in teams:
            raise ValueError(f"Team {block['ws_team_id']} gehört nicht zu Spiel {match.ws_match_id}")

    player_data: dict[int, dict] = {}
    referenced: set[int] = set()
    stat_keys: set[str] = set()
    for block in blocks:
        stat_keys.update(block["stats"])
        for player in block["players"]:
            player_data[player["ws_player_id"]] = player
            referenced.add(player["ws_player_id"])
            stat_keys.update(player["stats"])
        for formation in block["formations"]:
            if formation["captain_ws_player_id"] is not None:
                referenced.add(formation["captain_ws_player_id"])
            for position in formation["positions"]:
                if position["ws_player_id"] is not None:
                    referenced.add(position["ws_player_id"])
        for incident in block["incidents"]:
            for key in ("ws_player_id", "related_ws_player_id"):
                if incident[key] is not None:
                    referenced.add(incident[key])

    players = (
        {p.ws_player_id: p for p in db.scalars(select(Player).where(Player.ws_player_id.in_(referenced)))}
        if referenced
        else {}
    )
    stat_types = (
        {s.key: s for s in db.scalars(select(StatType).where(StatType.key.in_(stat_keys)))} if stat_keys else {}
    )
    venue = None
    if centre["venue_name"]:
        venue = db.scalars(select(Venue).where(Venue.name == centre["venue_name"])).first()
    referee = None
    referee_data = centre["referee"]
    if referee_data:
        referee = db.scalars(select(Referee).where(Referee.ws_official_id == referee_data["ws_official_id"])).first()
    manager_names = {b["manager_name"] for b in blocks if b["manager_name"]}
    managers = (
        {m.name: m for m in db.scalars(select(Manager).where(Manager.name.in_(manager_names)))}
        if manager_names
        else {}
    )
    match_teams = {mt.team_id: mt for mt in db.scalars(select(MatchTeam).where(MatchTeam.match_id == match_id))}
    appearances = {a.player_id: a for a in db.scalars(select(Appearance).where(Appearance.match_id == match_id))}
    player_stats: dict[tuple[int, int], PlayerMatchStat] = {}
    if appearances:
        for pms in db.scalars(
            select(PlayerMatchStat).where(
                PlayerMatchStat.appearance_id.in_([a.id for a in appearances.values()])
            )
        ):
            player_stats[(pms.appearance_id, pms.stat_type_id)] = pms
    team_stats = {
        (t.team_id, t.stat_type_id): t for t in db.scalars(select(TeamMatchStat).where(TeamMatchStat.match_id == match_id))
    }
    formations = {
        (f.team_id, f.start_minute): f for f in db.scalars(select(Formation).where(Formation.match_id == match_id))
    }
    positions: dict[tuple[int, int], FormationPosition] = {}
    if formations:
        for pos in db.scalars(
            select(FormationPosition).where(FormationPosition.formation_id.in_([f.id for f in formations.values()]))
        ):
            positions[(pos.formation_id, pos.slot)] = pos
    incidents = {i.ws_event_id: i for i in db.scalars(select(MatchIncident).where(MatchIncident.match_id == match_id))}

    # -- Stammdaten: neue Zeilen per Bulk-Insert (IDs über natürliche Schlüssel) -----
    player_ids = {ws_id: p.id for ws_id, p in players.items()}
    new_players: list[dict] = []
    for ws_id in sorted(referenced):
        data = player_data.get(ws_id)
        player = players.get(ws_id)
        if player is None:
            new_players.append(
                {
                    "ws_player_id": ws_id,
                    "name": (data or {}).get("name") or f"Unbekannt ({ws_id})",
                    "height": (data or {}).get("height"),
                    "weight": (data or {}).get("weight"),
                }
            )
        elif data:
            if data["name"]:
                _set_attr(player, "name", data["name"])
            _set_attr(player, "height", data["height"])
            _set_attr(player, "weight", data["weight"])
    player_ids.update(_bulk_insert_ids(db, Player, new_players, "ws_player_id"))

    stat_type_ids = {key: s.id for key, s in stat_types.items()}
    stat_type_ids.update(
        _bulk_insert_ids(db, StatType, [{"key": k} for k in sorted(stat_keys) if k not in stat_type_ids], "key")
    )

    venue_id = venue.id if venue is not None else None
    if centre["venue_name"] and venue is None:
        venue_id = _bulk_insert_ids(db, Venue, [{"name": centre["venue_name"]}], "name")[centre["venue_name"]]
    referee_id = referee.id if referee is not None else None
    if referee_data:
        if referee is None:
            referee_id = _bulk_insert_ids(
                db,
                Referee,
                [
                    {
                        "ws_official_id": referee_data["ws_official_id"],
                        "first_name": referee_data["first_name"],
                        "last_name": referee_data["last_name"],
                        "name": referee_data["name"] or f"Unbekannt ({referee_data['ws_official_id']})",
                    }
                ],
                "ws_official_id",
            )[referee_data["ws_official_id"]]
        else:
            if referee_data["name"]:
                _set_attr(referee, "name", referee_data["name"])
            _set_attr(referee, "first_name", referee_data["first_name"])
            _set_attr(referee, "last_name", referee_data["last_name"])
    manager_ids = {name: m.id for name, m in managers.items()}
    manager_ids.update(
        _bulk_insert_ids(db, Manager, [{"name": n} for n in sorted(manager_names) if n not in manager_ids], "name")
    )

    # -- Spiel --------------------------------------------------------------
    if venue_id is not None:
        _set_attr(match, "venue_id", venue_id)
    if referee_id is not None:
        _set_attr(match, "referee_id", referee_id)
    _set_attr(match, "attendance", centre["attendance"])
    for field in ("ht_home_score", "ht_away_score", "et_home_score", "et_away_score", "pen_home_score", "pen_away_score"):
        _set_attr(match, field, centre[field])
    if match.home_score is None:
        _set_attr(match, "home_score", centre["ft_home_score"])
    if match.away_score is None:
        _set_attr(match, "away_score", centre["ft_away_score"])
    became_finished = False
    if centre["is_finished"] and match.status != "finished":
        match.status = "finished"
        became_finished = True

    # -- Teams, Einsätze, Statistiken, Formationen, Ereignisse --------------
    any_first_eleven = False
    appearance_count = 0
    team_stat_count = 0
    new_match_teams: list[dict] = []
    new_appearances: list[dict] = []
    appearance_new_ids: set[int] = set()
    new_team_stats: list[dict] = []
    stat_rows: dict[int, dict] = {}
    for block in blocks:
        team = teams[block["ws_team_id"]]
        manager_id = manager_ids.get(block["manager_name"]) if block["manager_name"] else None
        match_team = match_teams.get(team.id)
        if match_team is None:
            new_match_teams.append(
                {
                    "match_id": match_id,
                    "team_id": team.id,
                    "manager_id": manager_id,
                    "average_age": block["average_age"],
                }
            )
        else:
            if manager_id is not None:
                _set_attr(match_team, "manager_id", manager_id)
            _set_attr(match_team, "average_age", block["average_age"])

        # Spieler je ws_player_id nur einmal (falls der Feed ihn doppelt liefert: letzter Eintrag gewinnt)
        block_players = {p["ws_player_id"]: p for p in block["players"]}
        for player_info in block_players.values():
            player_id = player_ids[player_info["ws_player_id"]]
            appearance = appearances.get(player_id)
            if appearance is None and player_id not in appearance_new_ids:
                appearance_new_ids.add(player_id)
                new_appearances.append(
                    {
                        "match_id": match_id,
                        "team_id": team.id,
                        "player_id": player_id,
                        "shirt_no": player_info["shirt_no"],
                        "position": player_info["position"],
                        "is_first_eleven": player_info["is_first_eleven"],
                        "is_man_of_the_match": player_info["is_man_of_the_match"],
                        "age": player_info["age"],
                        "rating": player_info["rating"],
                        "subbed_in_minute": player_info["subbed_in_minute"],
                        "subbed_out_minute": player_info["subbed_out_minute"],
                    }
                )
            elif appearance is not None:
                _set_attr(appearance, "team_id", team.id)
                for attr in ("shirt_no", "position", "age", "subbed_in_minute", "subbed_out_minute"):
                    _set_attr(appearance, attr, player_info[attr])
                _set_float(appearance, "rating", player_info["rating"])
                _set_attr(appearance, "is_first_eleven", player_info["is_first_eleven"])
                _set_attr(appearance, "is_man_of_the_match", player_info["is_man_of_the_match"])
            any_first_eleven = any_first_eleven or player_info["is_first_eleven"]
            appearance_count += 1
            stat_rows[player_id] = player_info["stats"]

        for key, value in block["stats"].items():
            stat_type_id = stat_type_ids[key]
            row = team_stats.get((team.id, stat_type_id))
            if row is None:
                new_team_stats.append(
                    {"match_id": match_id, "team_id": team.id, "stat_type_id": stat_type_id, "value": value}
                )
            else:
                _set_float(row, "value", value)
            team_stat_count += 1

    _bulk_insert(db, MatchTeam, new_match_teams)
    _bulk_insert(db, TeamMatchStat, new_team_stats)
    appearance_ids = {p: a.id for p, a in appearances.items() if a is not None}
    appearance_ids.update(_bulk_insert_ids(db, Appearance, new_appearances, "player_id"))

    # -- Formationen ---------------------------------------------------------
    # je (Team, Startminute) nur einmal (Duplikate im Feed: letzter Eintrag gewinnt)
    formation_rows: dict[tuple[int, int], dict] = {}
    for block in blocks:
        team_id = teams[block["ws_team_id"]].id
        for data in block["formations"]:
            formation_rows[(team_id, data["start_minute"])] = data
    new_formations: list[dict] = []
    formation_ids = {key: f.id for key, f in formations.items()}
    for key, data in formation_rows.items():
        captain_id = player_ids.get(data["captain_ws_player_id"]) if data["captain_ws_player_id"] is not None else None
        formation = formations.get(key)
        if formation is None:
            new_formations.append(
                {
                    "match_id": match_id,
                    "team_id": key[0],
                    "start_minute": key[1],
                    "end_minute": data["end_minute"],
                    "period": data["period"],
                    "name": data["name"],
                    "captain_player_id": captain_id,
                }
            )
        else:
            _set_attr(formation, "end_minute", data["end_minute"])
            _set_attr(formation, "period", data["period"])
            _set_attr(formation, "name", data["name"])
            if captain_id is not None:
                _set_attr(formation, "captain_player_id", captain_id)
    for row in _bulk_returning(db, Formation, new_formations, ("id", "team_id", "start_minute")):
        formation_ids[(row.team_id, row.start_minute)] = row.id

    # -- Ereignisse ------------------------------------------------------------
    new_incidents: list[dict] = []
    incident_count = 0
    seen_events: set[int] = set()
    for block in blocks:
        block_team = teams[block["ws_team_id"]]
        for data in block["incidents"]:
            if data["ws_event_id"] in seen_events:
                continue
            seen_events.add(data["ws_event_id"])
            team_id = teams.get(data["ws_team_id"], block_team).id
            player_id = player_ids.get(data["ws_player_id"]) if data["ws_player_id"] is not None else None
            related_id = (
                player_ids.get(data["related_ws_player_id"]) if data["related_ws_player_id"] is not None else None
            )
            incident = incidents.get(data["ws_event_id"])
            if incident is None:
                new_incidents.append(
                    {
                        "match_id": match_id,
                        "team_id": team_id,
                        "ws_event_id": data["ws_event_id"],
                        "type": data["type"],
                        "card_type": data["card_type"],
                        "minute": data["minute"],
                        "expanded_minute": data["expanded_minute"],
                        "period": data["period"],
                        "player_id": player_id,
                        "related_player_id": related_id,
                    }
                )
            else:
                _set_attr(incident, "team_id", team_id)
                _set_attr(incident, "type", data["type"])
                _set_attr(incident, "card_type", data["card_type"])
                _set_attr(incident, "minute", data["minute"])
                _set_attr(incident, "expanded_minute", data["expanded_minute"])
                _set_attr(incident, "period", data["period"])
                if player_id is not None:
                    _set_attr(incident, "player_id", player_id)
                if related_id is not None:
                    _set_attr(incident, "related_player_id", related_id)
            incident_count += 1
    _bulk_insert(db, MatchIncident, new_incidents)

    # -- Sync-Stand ---------------------------------------------------------
    state.last_attempt_at = now
    if not _is_upcoming(match.status, match.kickoff_time, now):
        state.attempts = (state.attempts or 0) + 1
    state.last_error = None
    state.details_synced_at = now
    if final:
        state.details_final_at = now
    if any_first_eleven and state.lineups_confirmed_at is None:
        state.lineups_confirmed_at = now

    # -- Abhängige Zeilen (brauchen Einsatz-/Formations-IDs) -----------------
    new_player_stats: list[dict] = []
    player_stat_count = 0
    for player_id, stats in stat_rows.items():
        appearance_id = appearance_ids[player_id]
        for key, value in stats.items():
            stat_type_id = stat_type_ids[key]
            row = player_stats.get((appearance_id, stat_type_id))
            if row is None:
                new_player_stats.append(
                    {"appearance_id": appearance_id, "stat_type_id": stat_type_id, "value": value}
                )
            else:
                _set_float(row, "value", value)
            player_stat_count += 1
    _bulk_insert(db, PlayerMatchStat, new_player_stats)

    new_positions: list[dict] = []
    for key, data in formation_rows.items():
        formation_id = formation_ids[key]
        for position in {p["slot"]: p for p in data["positions"]}.values():
            row = positions.get((formation_id, position["slot"]))
            position_player_id = (
                player_ids.get(position["ws_player_id"]) if position["ws_player_id"] is not None else None
            )
            if row is None:
                new_positions.append(
                    {
                        "formation_id": formation_id,
                        "slot": position["slot"],
                        "player_id": position_player_id,
                        "vertical": position["vertical"],
                        "horizontal": position["horizontal"],
                    }
                )
            else:
                if position_player_id is not None:
                    _set_attr(row, "player_id", position_player_id)
                _set_attr(row, "vertical", position["vertical"])
                _set_attr(row, "horizontal", position["horizontal"])
    _bulk_insert(db, FormationPosition, new_positions)

    return {
        "status": "ok",
        "appearances": appearance_count,
        "player_stats": player_stat_count,
        "team_stats": team_stat_count,
        "incidents": incident_count,
        "formations": len(formation_rows),
        "newly_finished": became_finished,
    }


def sync_match_details(db: Session, client: WhoScoredClient, match: Match, final: bool = False) -> dict:
    """Lädt das Match Centre eines Spiels und speichert es (eine Transaktion pro Spiel).

    Der Abrufversuch wird immer im ``MatchSyncState`` festgehalten (``last_attempt_at``). ``attempts`` (und
    bei „nicht verfügbar“ ``last_error``) zählen nur, wenn das Spiel nicht mehr bevorsteht (Status !=
    ``scheduled`` oder Anpfiff erreicht); Vorab-Versuche (Aufstellungen) verbrauchen so nicht das
    Nachlade-Budget des Schedulers. Fehler werden nicht geworfen,
    sondern als ``{"status": "error", "error": ...}`` zurückgegeben; ``{"status": "unavailable"}``,
    wenn WhoScored (noch) keine Daten hat. Erfolg:
    ``{"status": "ok", "appearances", "player_stats", "team_stats", "incidents", "formations",
    "newly_finished"}`` (``newly_finished``: durch die Details auf ``finished`` gesetzt).
    """
    match_id = match.id
    ws_match_id = match.ws_match_id

    try:
        centre = client.fetch_match_centre(ws_match_id)
    except WhoScoredError as exc:
        logger.warning("Match Centre %s nicht abrufbar: %s", ws_match_id, exc)
        _record_attempt(db, match_id, str(exc))
        return {"status": "error", "error": str(exc)}

    if centre is None:
        _record_attempt(db, match_id, "Match Centre nicht verfügbar", unavailable=True)
        return {"status": "unavailable"}

    try:
        result = _store_match_details(db, match, centre, final, _now())
        db.commit()
    except Exception as exc:  # noqa: BLE001 – nur dieses Spiel zurückrollen
        logger.exception("Match-Details %s konnten nicht gespeichert werden", ws_match_id)
        db.rollback()
        _record_attempt(db, match_id, f"{type(exc).__name__}: {exc}"[:500])
        return {"status": "error", "error": str(exc)}
    return result


# ---------------------------------------------------------------------------
# Fehlende Spieler (Preview)
# ---------------------------------------------------------------------------

def sync_missing_players(db: Session, client: WhoScoredClient, match: Match) -> dict:
    """Ersetzt die aktuellen Ausfälle beider Teams durch die der Spielvorschau.

    Nur für nicht beendete Spiele. Spieler, die nicht mehr in der Liste stehen, werden gelöscht.
    Eine Vorschau eines älteren Spiels überschreibt nie Daten einer neueren Vorschau.
    Rückgabe: ``{"status": "ok", "home": n, "away": n, "removed": n}``, bei WhoScored-Fehlern
    ``{"status": "error", "error": ...}`` (bestehende Daten bleiben), bei beendeten Spielen
    ``{"status": "skipped"}``.
    """
    match_id = match.id
    ws_match_id = match.ws_match_id
    if match.status == "finished":
        return {"status": "skipped", "reason": "finished"}

    try:
        data = client.fetch_missing_players(ws_match_id)
    except WhoScoredError as exc:
        logger.warning("Preview %s nicht abrufbar: %s", ws_match_id, exc)
        return {"status": "error", "error": str(exc)}

    now = _now()
    kickoff = match.kickoff_time
    team_ids = {"home": match.home_team_id, "away": match.away_team_id}
    try:
        existing = list(db.scalars(select(MissingPlayer).where(MissingPlayer.team_id.in_(list(team_ids.values())))))
        # Teams, für die bereits die Vorschau eines späteren Spiels synchronisiert wurde (Schutz vor Überschreiben)
        teams_with_newer: set[int] = set()
        if kickoff is not None:
            tids = list(team_ids.values())
            for home_id, away_id in db.execute(
                select(Match.home_team_id, Match.away_team_id)
                .join(MatchSyncState, MatchSyncState.match_id == Match.id)
                .where(
                    Match.id != match_id,
                    MatchSyncState.prematch_synced_at.is_not(None),
                    Match.kickoff_time > _to_berlin(kickoff),
                    or_(Match.home_team_id.in_(tids), Match.away_team_id.in_(tids)),
                )
            ):
                teams_with_newer.update((home_id, away_id))
        ws_ids = {p["ws_player_id"] for side in ("home", "away") for p in data[side]}
        players = (
            {p.ws_player_id: p for p in db.scalars(select(Player).where(Player.ws_player_id.in_(ws_ids)))}
            if ws_ids
            else {}
        )

        result = {"status": "ok", "home": 0, "away": 0, "removed": 0}
        for side in ("home", "away"):
            team_id = team_ids[side]
            rows = {r.player_id: r for r in existing if r.team_id == team_id}

            if team_id in teams_with_newer:
                logger.info(
                    "Preview %s (%s) ignoriert: Vorschau eines späteren Spiels bereits synchronisiert",
                    ws_match_id,
                    side,
                )
                continue

            for info in data[side]:
                player = players.get(info["ws_player_id"])
                if player is None:
                    player = Player(
                        ws_player_id=info["ws_player_id"], name=info["name"] or f"Unbekannt ({info['ws_player_id']})"
                    )
                    db.add(player)
                    players[info["ws_player_id"]] = player
                elif info["name"] and player.name.startswith("Unbekannt ("):
                    player.name = info["name"]
            db.flush()

            current_ids = set()
            for info in data[side]:
                player = players[info["ws_player_id"]]
                current_ids.add(player.id)
                row = rows.get(player.id)
                if row is None:
                    db.add(
                        MissingPlayer(
                            team_id=team_id,
                            player_id=player.id,
                            match_id=match_id,
                            reason=info["reason"],
                            status=info["status"],
                            updated_at=now,
                        )
                    )
                else:
                    changed = _set_attr(row, "reason", info["reason"], allow_none=True)
                    changed |= _set_attr(row, "status", info["status"], allow_none=True)
                    changed |= _set_attr(row, "match_id", match_id)
                    if changed:
                        row.updated_at = now
            result[side] = len(current_ids)
            for player_id, row in rows.items():
                if player_id not in current_ids:
                    db.delete(row)
                    result["removed"] += 1

        state = _get_or_create_state(db, match_id)
        state.prematch_synced_at = now
        db.commit()
    except Exception:
        db.rollback()
        raise
    return result


# ---------------------------------------------------------------------------
# Pre-Match (T-45min)
# ---------------------------------------------------------------------------

def sync_prematch(
    db: Session,
    client: WhoScoredClient,
    match: Match,
    refresh_fixtures: bool = True,
    has_preview: bool | None = None,
) -> dict:
    """Vorbereitung kurz vor Anpfiff: Fixture-Monat, Ausfälle (falls Preview) und ggf. Aufstellungen.

    ``refresh_fixtures=False``: der Aufrufer hat den Fixture-Monat bereits (gruppiert) per
    ``sync_stage_month`` geladen und übergibt ``has_preview`` aus dessen Ergebnis; es wird dann keine
    Fixture-Seite geladen.

    Rückgabe: ``{"fixture": {...}|{"status": ...}, "missing_players": {...}, "details": {...}}``.
    """
    match_id = match.id
    stage = db.get(Stage, match.stage_id)
    season = db.get(Season, stage.season_id)
    stage_ws_id = stage.ws_stage_id
    kickoff = _to_berlin(match.kickoff_time)
    ws_match_id = match.ws_match_id

    result: dict = {}
    preview = bool(has_preview) if not refresh_fixtures else False
    if not refresh_fixtures:
        result["fixture"] = {"status": "skipped", "reason": "group_refresh"}
    elif kickoff is not None:
        try:
            summary, seen = _sync_fixtures(db, client, season, [(kickoff.year, kickoff.month)], {stage_ws_id})
            result["fixture"] = summary
            fixture = seen.get(ws_match_id)
            preview = bool(fixture and fixture.get("has_preview"))
        except WhoScoredError as exc:
            logger.warning("Fixture-Refresh für Spiel %s fehlgeschlagen: %s", ws_match_id, exc)
            db.rollback()
            result["fixture"] = {"status": "error", "error": str(exc)}
    else:
        result["fixture"] = {"status": "skipped"}

    match = db.get(Match, match_id)
    if preview:
        result["missing_players"] = sync_missing_players(db, client, match)
    else:
        result["missing_players"] = {"status": "skipped", "reason": "no_preview"}

    result["details"] = sync_match_details(db, client, db.get(Match, match_id))
    return result


# ---------------------------------------------------------------------------
# Backfill / Admin
# ---------------------------------------------------------------------------

def _import_season(
    db: Session,
    client: WhoScoredClient,
    league_key: str,
    season_code: str,
    with_details: bool,
    max_matches: int | None,
) -> dict:
    pages_before = _pages(client)
    season = ensure_season(db, client, league_key, season_code)
    season_id, code = season.id, season.code
    fixtures = sync_fixtures(db, client, season)

    details = {"pending": 0, "attempted": 0, "ok": 0, "unavailable": 0, "errors": 0}
    if with_details:
        pending_ids = list(
            db.scalars(
                select(Match.id)
                .join(Stage, Stage.id == Match.stage_id)
                .outerjoin(MatchSyncState, MatchSyncState.match_id == Match.id)
                .where(
                    Stage.season_id == season_id,
                    Match.status == "finished",
                    MatchSyncState.details_final_at.is_(None),
                )
                .order_by(Match.kickoff_time, Match.id)
            )
        )
        details["pending"] = len(pending_ids)
        todo = pending_ids if max_matches is None else pending_ids[: max(0, max_matches)]
        for index, match_id in enumerate(todo, start=1):
            match = db.get(Match, match_id)
            label = f"{match.ws_match_id}"
            result = sync_match_details(db, client, match, final=True)
            details["attempted"] += 1
            status = result["status"]
            if status == "ok":
                details["ok"] += 1
            elif status == "unavailable":
                details["unavailable"] += 1
            else:
                details["errors"] += 1
            logger.info("[%d/%d] Spiel %s: %s", index, len(todo), label, status)

    return {
        "league_key": league_key,
        "season_code": code,
        "fixtures": fixtures,
        "details": details,
        "pages": _pages(client) - pages_before,
    }


def import_season(
    db: Session,
    league_key: str,
    season_code: str,
    with_details: bool = True,
    client: WhoScoredClient | None = None,
    max_matches: int | None = None,
) -> dict:
    """Backfill einer Saison: Metadaten, kompletter Spielplan, Details aller beendeten Spiele.

    Wiederaufnehmbar: Spiele mit ``details_final_at`` werden übersprungen. ``max_matches``
    begrenzt die Anzahl der Detail-Abrufe. Ohne ``client`` wird ein eigener geöffnet.
    """
    get_competition_config(league_key)
    if client is not None:
        return _import_season(db, client, league_key, season_code, with_details, max_matches)
    with WhoScoredClient() as own_client:
        return _import_season(db, own_client, league_key, season_code, with_details, max_matches)


def sync_match_by_ws_id(db: Session, ws_match_id: int, final: bool = False) -> dict:
    """Admin-Komfort: lädt die Details eines bereits bekannten Spiels (eigener Browser)."""
    match = db.scalars(select(Match).where(Match.ws_match_id == ws_match_id)).first()
    if match is None:
        raise ValueError(f"Spiel mit ws_match_id {ws_match_id} ist nicht in der Datenbank")
    with WhoScoredClient() as client:
        return sync_match_details(db, client, match, final=final)
