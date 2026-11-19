"""Lesezugriffe für die Fußball-Endpunkte (WhoScored-Datenmodell).

Reine Lese-Logik ohne externe Aufrufe. Abgeleitete Daten (z. B. die Tabelle) werden
nicht gespeichert, sondern bei Bedarf aus den abgeschlossenen Spielen berechnet (3NF).
Die Abfragen sind bewusst auf wenige Round-Trips ausgelegt (Remote-DB): Beziehungen
werden per ``joinedload`` geladen, Detaildaten per ``IN``-Abfragen gebündelt.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import (
    Appearance,
    Competition,
    Formation,
    FormationPosition,
    Match,
    MatchIncident,
    MatchSyncState,
    MatchTeam,
    MissingPlayer,
    Player,
    PlayerMatchStat,
    Season,
    Stage,
    StatType,
    Team,
    TeamMatchStat,
)

BERLIN = ZoneInfo("Europe/Berlin")

# Spielzeit-Grenzen der Perioden, ab denen die Nachspielzeit-Notation greift.
_PERIOD_LIMITS = {"first_half": 45, "second_half": 90, "et_first": 105, "et_second": 120}


# ── Hilfsfunktionen ──────────────────────────────────────────────────────────

def _period_limit(period: str | None) -> int | None:
    if not period:
        return None
    p = period.replace(" ", "").replace("_", "").lower()
    if "extra" in p:
        if "first" in p:
            return _PERIOD_LIMITS["et_first"]
        if "second" in p:
            return _PERIOD_LIMITS["et_second"]
        return None
    if p == "firsthalf":
        return _PERIOD_LIMITS["first_half"]
    if p == "secondhalf":
        return _PERIOD_LIMITS["second_half"]
    return None


def format_minute(minute: int, period: str | None) -> str:
    """Formatiert die (0-basierte) WhoScored-Minute für die Anzeige.

    Anzeige-Minute = ``minute + 1``. Liegt sie über der Periodengrenze (45/90/105/120),
    wird die Nachspielzeit als ``"45+2"`` ausgegeben.
    """
    display = minute + 1
    limit = _period_limit(period)
    if limit is not None and display > limit:
        return f"{limit}+{display - limit}"
    return str(display)


def _day_start(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=BERLIN)


# ── Wettbewerbe & Saisons ────────────────────────────────────────────────────

def list_competitions(db: Session) -> list[tuple[Competition, list[str]]]:
    """Alle Wettbewerbe samt Saison-Codes (neueste zuerst) in zwei Abfragen."""
    competitions = db.scalars(
        select(Competition).options(joinedload(Competition.region)).order_by(Competition.name)
    ).all()
    seasons_by_comp: dict[int, list[str]] = defaultdict(list)
    for comp_id, code in db.execute(
        select(Season.competition_id, Season.code).order_by(Season.code.desc())
    ):
        seasons_by_comp[comp_id].append(code)
    return [(c, seasons_by_comp.get(c.id, [])) for c in competitions]


def get_competition_by_slug(db: Session, slug: str) -> Competition | None:
    return db.scalars(
        select(Competition).options(joinedload(Competition.region)).where(Competition.slug == slug)
    ).first()


def list_seasons(db: Session, competition: Competition) -> list[Season]:
    return list(
        db.scalars(
            select(Season).where(Season.competition_id == competition.id).order_by(Season.code.desc())
        )
    )


def resolve_season(db: Session, competition: Competition, season_code: str | None) -> Season | None:
    """Liefert die Saison zum Code; ohne Code die neueste (aktuelle) Saison."""
    stmt = select(Season).where(Season.competition_id == competition.id)
    if season_code is not None:
        stmt = stmt.where(Season.code == season_code)
    return db.scalars(stmt.order_by(Season.code.desc())).first()


# ── Spiele ───────────────────────────────────────────────────────────────────

def _match_options():
    return (
        joinedload(Match.home_team),
        joinedload(Match.away_team),
        joinedload(Match.stage).joinedload(Stage.season).joinedload(Season.competition),
    )


def list_matches(
    db: Session,
    *,
    season_id: int | None = None,
    competition_id: int | None = None,
    season_code: str | None = None,
    team_id: int | None = None,
    status: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[Match]:
    """Spiele nach Kriterien gefiltert, nach Anstoßzeit sortiert (inkl. Teams/Stage geladen)."""
    stmt = select(Match).join(Stage, Match.stage_id == Stage.id).options(*_match_options())
    if season_id is not None or competition_id is not None or season_code is not None:
        stmt = stmt.join(Season, Stage.season_id == Season.id)
    if season_id is not None:
        stmt = stmt.where(Stage.season_id == season_id)
    if competition_id is not None:
        stmt = stmt.where(Season.competition_id == competition_id)
    if season_code is not None:
        stmt = stmt.where(Season.code == season_code)
    if team_id is not None:
        stmt = stmt.where(or_(Match.home_team_id == team_id, Match.away_team_id == team_id))
    if status is not None:
        stmt = stmt.where(Match.status == status)
    if date_from is not None:
        stmt = stmt.where(Match.kickoff_time >= _day_start(date_from))
    if date_to is not None:
        stmt = stmt.where(Match.kickoff_time < _day_start(date_to + timedelta(days=1)))
    return list(db.scalars(stmt.order_by(Match.kickoff_time, Match.id)).unique())


def get_match(db: Session, match_id: int) -> Match | None:
    return db.scalars(
        select(Match)
        .options(*_match_options(), joinedload(Match.venue), joinedload(Match.referee))
        .where(Match.id == match_id)
    ).first()


def _players_by_id(db: Session, ids: set[int]) -> dict[int, Player]:
    if not ids:
        return {}
    return {p.id: p for p in db.scalars(select(Player).where(Player.id.in_(ids)))}


def get_match_detail(db: Session, match: Match) -> dict:
    """Bündelt alle Detaildaten eines Spiels (Trainer, Formationen, Ereignisse, Sync-Stand)."""
    match_teams = {
        mt.team_id: mt
        for mt in db.scalars(
            select(MatchTeam).options(joinedload(MatchTeam.manager)).where(MatchTeam.match_id == match.id)
        )
    }
    formations = list(
        db.scalars(
            select(Formation)
            .where(Formation.match_id == match.id)
            .order_by(Formation.team_id, Formation.start_minute)
        )
    )
    positions_by_formation: dict[int, list[FormationPosition]] = defaultdict(list)
    if formations:
        for pos in db.scalars(
            select(FormationPosition)
            .where(FormationPosition.formation_id.in_([f.id for f in formations]))
            .order_by(FormationPosition.formation_id, FormationPosition.slot)
        ):
            positions_by_formation[pos.formation_id].append(pos)

    incidents = list(
        db.scalars(
            select(MatchIncident)
            .where(MatchIncident.match_id == match.id)
            .order_by(func.coalesce(MatchIncident.expanded_minute, MatchIncident.minute), MatchIncident.id)
        )
    )

    player_ids: set[int] = set()
    for f in formations:
        if f.captain_player_id:
            player_ids.add(f.captain_player_id)
        player_ids.update(p.player_id for p in positions_by_formation[f.id] if p.player_id)
    for inc in incidents:
        if inc.player_id:
            player_ids.add(inc.player_id)
        if inc.related_player_id:
            player_ids.add(inc.related_player_id)

    return {
        "match_teams": match_teams,
        "formations": formations,
        "positions": positions_by_formation,
        "incidents": incidents,
        "players": _players_by_id(db, player_ids),
        "sync_state": db.get(MatchSyncState, match.id),
    }


def get_lineups(db: Session, match_id: int) -> list[Appearance]:
    return list(
        db.scalars(
            select(Appearance)
            .options(joinedload(Appearance.player))
            .where(Appearance.match_id == match_id)
            .order_by(Appearance.is_first_eleven.desc(), Appearance.shirt_no, Appearance.id)
        )
    )


def get_team_stats(db: Session, match_id: int) -> dict[int, dict[str, float]]:
    stats: dict[int, dict[str, float]] = defaultdict(dict)
    rows = db.execute(
        select(TeamMatchStat.team_id, StatType.key, TeamMatchStat.value)
        .join(StatType, TeamMatchStat.stat_type_id == StatType.id)
        .where(TeamMatchStat.match_id == match_id)
        .order_by(StatType.key)
    )
    for team_id, key, value in rows:
        stats[team_id][key] = value
    return dict(stats)


def get_player_stats(db: Session, match_id: int) -> list[tuple[Appearance, dict[str, float]]]:
    """Einsätze eines Spiels mit ihren Statistiken (nur Spieler mit Statistik oder Bewertung)."""
    appearances = get_lineups(db, match_id)
    by_appearance: dict[int, dict[str, float]] = defaultdict(dict)
    if appearances:
        rows = db.execute(
            select(PlayerMatchStat.appearance_id, StatType.key, PlayerMatchStat.value)
            .join(StatType, PlayerMatchStat.stat_type_id == StatType.id)
            .where(PlayerMatchStat.appearance_id.in_([a.id for a in appearances]))
            .order_by(StatType.key)
        )
        for appearance_id, key, value in rows:
            by_appearance[appearance_id][key] = value
    return [
        (a, by_appearance.get(a.id, {}))
        for a in appearances
        if a.id in by_appearance or a.rating is not None
    ]


# ── Teams ────────────────────────────────────────────────────────────────────

def _season_team_ids_subquery(season_id: int):
    stage_ids = select(Stage.id).where(Stage.season_id == season_id)
    home = select(Match.home_team_id.label("team_id")).where(Match.stage_id.in_(stage_ids))
    away = select(Match.away_team_id.label("team_id")).where(Match.stage_id.in_(stage_ids))
    return home.union(away).subquery()


def list_season_teams(db: Session, season_id: int) -> list[Team]:
    sub = _season_team_ids_subquery(season_id)
    return list(
        db.scalars(
            select(Team)
            .options(joinedload(Team.country))
            .where(Team.id.in_(select(sub.c.team_id)))
            .order_by(Team.name)
        )
    )


def get_team(db: Session, team_id: int) -> Team | None:
    return db.scalars(
        select(Team).options(joinedload(Team.country)).where(Team.id == team_id)
    ).first()


def list_missing_players(
    db: Session, *, team_id: int | None = None, season_id: int | None = None
) -> list[tuple[MissingPlayer, Player, Team]]:
    stmt = (
        select(MissingPlayer, Player, Team)
        .join(Player, MissingPlayer.player_id == Player.id)
        .join(Team, MissingPlayer.team_id == Team.id)
    )
    if team_id is not None:
        stmt = stmt.where(MissingPlayer.team_id == team_id)
    if season_id is not None:
        sub = _season_team_ids_subquery(season_id)
        stmt = stmt.where(MissingPlayer.team_id.in_(select(sub.c.team_id)))
    return [tuple(row) for row in db.execute(stmt.order_by(Team.name, Player.name))]


# ── Tabelle ──────────────────────────────────────────────────────────────────

def _blank_row(team_id: int, name: str) -> dict:
    return {
        "team_id": team_id,
        "name": name,
        "played": 0,
        "won": 0,
        "drawn": 0,
        "lost": 0,
        "goals_for": 0,
        "goals_against": 0,
        "points": 0,
        "results": [],
    }


def _apply_result(row: dict, goals_for: int, goals_against: int) -> None:
    row["played"] += 1
    row["goals_for"] += goals_for
    row["goals_against"] += goals_against
    if goals_for > goals_against:
        row["won"] += 1
        row["points"] += 3
        row["results"].append("W")
    elif goals_for == goals_against:
        row["drawn"] += 1
        row["points"] += 1
        row["results"].append("D")
    else:
        row["lost"] += 1
        row["results"].append("L")


def _head_to_head(group: list[dict], finished: list) -> dict[int, tuple[int, int, int]]:
    """Mini-Tabelle (Punkte, Tordifferenz, Auswärtstore) nur aus Spielen unter den Teams der Gruppe."""
    ids = {r["team_id"] for r in group}
    h2h = {i: [0, 0, 0] for i in ids}
    for m in finished:
        if m.home_team_id not in ids or m.away_team_id not in ids:
            continue
        hs, as_ = m.home_score, m.away_score
        h2h[m.home_team_id][1] += hs - as_
        h2h[m.away_team_id][1] += as_ - hs
        h2h[m.away_team_id][2] += as_
        if hs > as_:
            h2h[m.home_team_id][0] += 3
        elif hs < as_:
            h2h[m.away_team_id][0] += 3
        else:
            h2h[m.home_team_id][0] += 1
            h2h[m.away_team_id][0] += 1
    return {i: (v[0], v[1], v[2]) for i, v in h2h.items()}


def compute_standings(db: Session, season_id: int) -> list[dict]:
    """Berechnet die Tabelle aus den abgeschlossenen Spielen der Standard-Stage(s) einer Saison.

    Sortierung: Punkte → Tordifferenz → erzielte Tore → direkter Vergleich (Punkte,
    Tordifferenz, Auswärtstore; nur unter punkt-/tor-gleichen Teams) → Teamname
    (deterministischer Fallback). Teams ohne Spiel erscheinen mit 0 Spielen.
    """
    stages = list(db.scalars(select(Stage).where(Stage.season_id == season_id)))
    stage_ids = [s.id for s in stages if s.is_default] or [s.id for s in stages]
    if not stage_ids:
        return []

    matches = list(
        db.execute(
            select(
                Match.home_team_id,
                Match.away_team_id,
                Match.status,
                Match.home_score,
                Match.away_score,
            )
            .where(Match.stage_id.in_(stage_ids))
            .order_by(Match.kickoff_time, Match.id)
        )
    )
    if not matches:
        return []

    team_ids = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
    names = {tid: name for tid, name in db.execute(select(Team.id, Team.name).where(Team.id.in_(team_ids)))}
    rows = {tid: _blank_row(tid, names.get(tid, "")) for tid in team_ids}

    finished = [
        m for m in matches if m.status == "finished" and m.home_score is not None and m.away_score is not None
    ]
    for m in finished:
        _apply_result(rows[m.home_team_id], m.home_score, m.away_score)
        _apply_result(rows[m.away_team_id], m.away_score, m.home_score)

    for r in rows.values():
        r["goal_difference"] = r["goals_for"] - r["goals_against"]

    # Primärsortierung, danach Gruppen mit identischem (Punkte, GD, GF) per direktem Vergleich auflösen.
    ordered = sorted(
        rows.values(), key=lambda r: (-r["points"], -r["goal_difference"], -r["goals_for"], r["name"])
    )
    result: list[dict] = []
    i = 0
    while i < len(ordered):
        j = i + 1
        key = (ordered[i]["points"], ordered[i]["goal_difference"], ordered[i]["goals_for"])
        while j < len(ordered) and (
            ordered[j]["points"], ordered[j]["goal_difference"], ordered[j]["goals_for"]
        ) == key:
            j += 1
        group = ordered[i:j]
        if len(group) > 1:
            h2h = _head_to_head(group, finished)
            group = sorted(
                group,
                key=lambda r: (-h2h[r["team_id"]][0], -h2h[r["team_id"]][1], -h2h[r["team_id"]][2], r["name"]),
            )
        result.extend(group)
        i = j

    return [
        {
            "position": pos,
            "team": {"id": r["team_id"], "name": r["name"]},
            "played": r["played"],
            "won": r["won"],
            "drawn": r["drawn"],
            "lost": r["lost"],
            "goals_for": r["goals_for"],
            "goals_against": r["goals_against"],
            "goal_difference": r["goal_difference"],
            "points": r["points"],
            "form": r["results"][-5:],
        }
        for pos, r in enumerate(result, start=1)
    ]
