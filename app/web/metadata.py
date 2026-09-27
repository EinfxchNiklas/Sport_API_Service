"""Kuratiertes Architektur-Modell: Endpunkte -> Services -> Datenquellen/Tabellen -> Scheduler.

Dient als Datengrundlage für den interaktiven Graph auf /admin/architecture.
Wird manuell gepflegt (siehe README-Hinweis unten), da eine Laufzeit-Introspektion
der Service-/DB-Aufrufe in Python nicht zuverlässig automatisch ableitbar ist.

Pflegehinweis: Beim Hinzufügen neuer Endpunkte/Services bitte NODES und EDGES ergänzen.
"""
from __future__ import annotations

from fastapi import FastAPI

NODES: dict[str, dict] = {
    # ── Datenquellen (externe APIs) ─────────────────────────────────────────
    "ds:openf1": {"label": "OpenF1 API", "type": "datasource", "detail": "api.openf1.org – öffentliche F1-Daten (kein Auth)"},
    "ds:api_football": {"label": "API-Football", "type": "datasource", "detail": "v3.football.api-sports.io – Bundesliga/Fußballdaten (RapidAPI-Key)"},
    "ds:tank01": {"label": "Tank01 NFL API", "type": "datasource", "detail": "RapidAPI – NFL-Teams/Spiele/Standings"},

    # ── DB-Tabellen ──────────────────────────────────────────────────────────
    "tbl:competitions": {"label": "competitions", "type": "table", "detail": "app/models/competition.py"},
    "tbl:teams": {"label": "teams", "type": "table", "detail": "app/models/team.py"},
    "tbl:matches": {"label": "matches", "type": "table", "detail": "app/models/match.py"},
    "tbl:players": {"label": "players", "type": "table", "detail": "app/models/player.py"},
    "tbl:injuries": {"label": "injuries", "type": "table", "detail": "app/models/injury.py"},
    "tbl:standings": {"label": "standings", "type": "table", "detail": "app/models/standing.py"},
    "tbl:drivers": {"label": "drivers", "type": "table", "detail": "app/models/driver.py"},
    "tbl:races": {"label": "races", "type": "table", "detail": "app/models/race.py"},
    "tbl:race_sessions": {"label": "race_sessions", "type": "table", "detail": "app/models/race_session.py"},
    "tbl:session_results": {"label": "session_results", "type": "table", "detail": "app/models/session_result.py"},
    "tbl:driver_standings": {"label": "driver_standings", "type": "table", "detail": "app/models/f1_standing.py"},
    "tbl:constructor_standings": {"label": "constructor_standings", "type": "table", "detail": "app/models/f1_standing.py"},
    "tbl:nfl_teams": {"label": "nfl_teams", "type": "table", "detail": "app/models/nfl_team.py"},
    "tbl:nfl_games": {"label": "nfl_games", "type": "table", "detail": "app/models/nfl_game.py"},
    "tbl:nfl_standings": {"label": "nfl_standings", "type": "table", "detail": "app/models/nfl_standing.py"},

    # ── Services ─────────────────────────────────────────────────────────────
    "svc:import_f1_races": {"label": "import_f1_races()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_f1_drivers": {"label": "import_f1_drivers()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_f1_sessions": {"label": "import_f1_sessions()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_f1_sessions_for_race": {"label": "import_f1_sessions_for_race()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_f1_session_results": {"label": "import_f1_session_results()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_f1_standings": {"label": "import_f1_standings()", "type": "service", "detail": "app/services/f1_service.py"},
    "svc:import_bundesliga": {"label": "import_bundesliga()", "type": "service", "detail": "app/services/football_service.py"},
    "svc:import_standings": {"label": "import_standings()", "type": "service", "detail": "app/services/football_service.py"},
    "svc:import_injuries": {"label": "import_injuries()", "type": "service", "detail": "app/services/football_service.py"},
    "svc:import_football_competition": {"label": "import_football_competition()", "type": "service", "detail": "app/services/football_service.py – orchestriert Teams/Tabelle/Verletzte"},
    "svc:import_nfl_teams": {"label": "import_nfl_teams()", "type": "service", "detail": "app/services/nfl_service.py"},
    "svc:import_nfl_games": {"label": "import_nfl_games()", "type": "service", "detail": "app/services/nfl_service.py – legacy matches-Tabelle"},
    "svc:import_nfl_games_new": {"label": "import_nfl_games_new()", "type": "service", "detail": "app/services/nfl_service.py – nfl_games-Tabelle"},
    "svc:import_nfl_standings": {"label": "import_nfl_standings()", "type": "service", "detail": "app/services/nfl_service.py"},

    # ── Scheduler-Jobs ───────────────────────────────────────────────────────
    "job:nightly_session_status_update": {"label": "nightly_session_status_update", "type": "job", "detail": "Cron täglich 03:00 – RaceSession-Status upcoming→completed"},
    "job:hourly_f1_data_fetch": {"label": "hourly_f1_data_fetch", "type": "job", "detail": "Interval 1h – lädt fehlende F1-Session-Ergebnisse nach, aktualisiert Standings"},
    "job:match_monitor": {"label": "match-{id} (dynamisch)", "type": "job", "detail": "Interval 2min ab geschätztem Spielende – überwacht ein einzelnes Bundesliga-Match, entfernt sich nach Spielende selbst"},

    # ── Endpunkte ────────────────────────────────────────────────────────────
    "ep:GET:/api/v1/health": {"label": "GET /health", "type": "endpoint", "method": "GET", "path": "/api/v1/health"},

    "ep:GET:/api/v1/f1/races": {"label": "GET /f1/races", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/races"},
    "ep:GET:/api/v1/f1/drivers": {"label": "GET /f1/drivers", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/drivers"},
    "ep:GET:/api/v1/f1/races/{race_id}/sessions": {"label": "GET /f1/races/{id}/sessions", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/races/{race_id}/sessions"},
    "ep:GET:/api/v1/f1/sessions/{session_id}/results": {"label": "GET /f1/sessions/{id}/results", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/sessions/{session_id}/results"},
    "ep:GET:/api/v1/f1/standings/drivers": {"label": "GET /f1/standings/drivers", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/standings/drivers"},

    "ep:GET:/api/v1/bundesliga/table": {"label": "GET /bundesliga/table", "type": "endpoint", "method": "GET", "path": "/api/v1/bundesliga/table"},
    "ep:GET:/api/v1/bundesliga/matches": {"label": "GET /bundesliga/matches", "type": "endpoint", "method": "GET", "path": "/api/v1/bundesliga/matches"},
    "ep:GET:/api/v1/bundesliga/standings": {"label": "GET /bundesliga/standings", "type": "endpoint", "method": "GET", "path": "/api/v1/bundesliga/standings"},
    "ep:GET:/api/v1/bundesliga/injuries": {"label": "GET /bundesliga/injuries", "type": "endpoint", "method": "GET", "path": "/api/v1/bundesliga/injuries"},

    "ep:GET:/api/v1/nfl/teams": {"label": "GET /nfl/teams", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/teams"},
    "ep:GET:/api/v1/nfl/games": {"label": "GET /nfl/games", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/games"},
    "ep:GET:/api/v1/nfl/standings": {"label": "GET /nfl/standings", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/standings"},

    "ep:POST:/api/v1/admin/import/bundesliga": {"label": "POST /admin/import/bundesliga", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/bundesliga"},
    "ep:POST:/api/v1/admin/import/football": {"label": "POST /admin/import/football", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/football"},
    "ep:POST:/api/v1/admin/import/f1/races": {"label": "POST /admin/import/f1/races", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/races"},
    "ep:POST:/api/v1/admin/import/f1/drivers": {"label": "POST /admin/import/f1/drivers", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/drivers"},
    "ep:POST:/api/v1/admin/import/f1/sessions": {"label": "POST /admin/import/f1/sessions", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/sessions"},
    "ep:POST:/api/v1/admin/import/f1/session-results": {"label": "POST /admin/import/f1/session-results", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/session-results"},
    "ep:POST:/api/v1/admin/import/f1/standings": {"label": "POST /admin/import/f1/standings", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/standings"},
    "ep:POST:/api/v1/admin/import/nfl/teams": {"label": "POST /admin/import/nfl/teams", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/teams"},
    "ep:POST:/api/v1/admin/import/nfl/games": {"label": "POST /admin/import/nfl/games", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/games"},
    "ep:POST:/api/v1/admin/import/nfl/games-new": {"label": "POST /admin/import/nfl/games-new", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/games-new"},
    "ep:POST:/api/v1/admin/import/nfl/standings": {"label": "POST /admin/import/nfl/standings", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/standings"},
}

# (source, target, edge_type) — edge_type in {"calls", "fetches", "reads", "writes", "triggers"}
EDGES: list[tuple[str, str, str]] = [
    # F1 GET-Endpunkte lösen bei Bedarf (Cache-Miss) den passenden Import an
    ("ep:GET:/api/v1/f1/races", "svc:import_f1_races", "calls"),
    ("ep:GET:/api/v1/f1/drivers", "svc:import_f1_drivers", "calls"),
    ("ep:GET:/api/v1/f1/races/{race_id}/sessions", "svc:import_f1_sessions_for_race", "calls"),
    ("ep:GET:/api/v1/f1/races/{race_id}/sessions", "svc:import_f1_sessions", "calls"),
    ("ep:GET:/api/v1/f1/sessions/{session_id}/results", "svc:import_f1_session_results", "calls"),
    ("ep:GET:/api/v1/f1/sessions/{session_id}/results", "svc:import_f1_drivers", "calls"),
    ("ep:GET:/api/v1/f1/standings/drivers", "svc:import_f1_standings", "calls"),

    ("ep:GET:/api/v1/bundesliga/table", "svc:import_bundesliga", "calls"),
    ("ep:GET:/api/v1/bundesliga/matches", "svc:import_bundesliga", "calls"),
    ("ep:GET:/api/v1/bundesliga/standings", "svc:import_standings", "calls"),
    ("ep:GET:/api/v1/bundesliga/injuries", "svc:import_injuries", "calls"),

    ("ep:GET:/api/v1/nfl/teams", "svc:import_nfl_teams", "calls"),
    ("ep:GET:/api/v1/nfl/games", "svc:import_nfl_games_new", "calls"),
    ("ep:GET:/api/v1/nfl/games", "svc:import_nfl_games", "calls"),
    ("ep:GET:/api/v1/nfl/standings", "svc:import_nfl_standings", "calls"),

    # Admin-Endpunkte lösen die gleichen Services aus (erzwungener Re-Import)
    ("ep:POST:/api/v1/admin/import/bundesliga", "svc:import_bundesliga", "calls"),
    ("ep:POST:/api/v1/admin/import/football", "svc:import_football_competition", "calls"),
    ("svc:import_football_competition", "svc:import_bundesliga", "calls"),
    ("svc:import_football_competition", "svc:import_standings", "calls"),
    ("svc:import_football_competition", "svc:import_injuries", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/races", "svc:import_f1_races", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/drivers", "svc:import_f1_drivers", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/sessions", "svc:import_f1_sessions", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/session-results", "svc:import_f1_session_results", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/standings", "svc:import_f1_standings", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/teams", "svc:import_nfl_teams", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/games", "svc:import_nfl_games", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/games-new", "svc:import_nfl_games_new", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/standings", "svc:import_nfl_standings", "calls"),

    # Services -> externe Datenquellen
    ("svc:import_f1_races", "ds:openf1", "fetches"),
    ("svc:import_f1_drivers", "ds:openf1", "fetches"),
    ("svc:import_f1_sessions", "ds:openf1", "fetches"),
    ("svc:import_f1_sessions_for_race", "ds:openf1", "fetches"),
    ("svc:import_f1_session_results", "ds:openf1", "fetches"),
    ("svc:import_f1_standings", "ds:openf1", "fetches"),
    ("svc:import_bundesliga", "ds:api_football", "fetches"),
    ("svc:import_standings", "ds:api_football", "fetches"),
    ("svc:import_injuries", "ds:api_football", "fetches"),
    ("svc:import_nfl_teams", "ds:tank01", "fetches"),
    ("svc:import_nfl_games", "ds:tank01", "fetches"),
    ("svc:import_nfl_games_new", "ds:tank01", "fetches"),
    ("svc:import_nfl_standings", "ds:tank01", "fetches"),

    # Services <-> DB-Tabellen
    ("svc:import_f1_races", "tbl:races", "writes"),
    ("svc:import_f1_drivers", "tbl:drivers", "writes"),
    ("svc:import_f1_sessions", "tbl:race_sessions", "writes"),
    ("svc:import_f1_sessions", "tbl:races", "reads"),
    ("svc:import_f1_sessions_for_race", "tbl:race_sessions", "writes"),
    ("svc:import_f1_session_results", "tbl:session_results", "writes"),
    ("svc:import_f1_session_results", "tbl:drivers", "reads"),
    ("svc:import_f1_session_results", "tbl:race_sessions", "reads"),
    ("svc:import_f1_standings", "tbl:driver_standings", "writes"),
    ("svc:import_f1_standings", "tbl:constructor_standings", "writes"),
    ("svc:import_f1_standings", "tbl:drivers", "reads"),

    ("svc:import_bundesliga", "tbl:competitions", "writes"),
    ("svc:import_bundesliga", "tbl:teams", "writes"),
    ("svc:import_bundesliga", "tbl:matches", "writes"),
    ("svc:import_standings", "tbl:standings", "writes"),
    ("svc:import_standings", "tbl:teams", "reads"),
    ("svc:import_standings", "tbl:competitions", "reads"),
    ("svc:import_injuries", "tbl:players", "writes"),
    ("svc:import_injuries", "tbl:injuries", "writes"),
    ("svc:import_injuries", "tbl:teams", "reads"),

    ("svc:import_nfl_teams", "tbl:nfl_teams", "writes"),
    ("svc:import_nfl_games", "tbl:teams", "writes"),
    ("svc:import_nfl_games", "tbl:matches", "writes"),
    ("svc:import_nfl_games", "tbl:competitions", "writes"),
    ("svc:import_nfl_games_new", "tbl:nfl_games", "writes"),
    ("svc:import_nfl_games_new", "tbl:nfl_teams", "reads"),
    ("svc:import_nfl_standings", "tbl:nfl_standings", "writes"),
    ("svc:import_nfl_standings", "tbl:nfl_teams", "reads"),

    # Scheduler-Jobs -> Services / Tabellen
    ("job:nightly_session_status_update", "tbl:race_sessions", "writes"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_session_results", "triggers"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_drivers", "triggers"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_standings", "triggers"),
    ("job:match_monitor", "tbl:matches", "reads"),
]


def get_architecture_graph() -> dict:
    """Statischer, kuratierter Graph als JSON-Struktur für Cytoscape.js."""
    nodes = [{"data": {"id": node_id, **attrs}} for node_id, attrs in NODES.items()]
    edges = [
        {"data": {"id": f"e{i}", "source": src, "target": tgt, "type": etype}}
        for i, (src, tgt, etype) in enumerate(EDGES)
    ]
    return {"nodes": nodes, "edges": edges}


def introspect_endpoints(app: FastAPI) -> list[dict]:
    """Liest die tatsächlich registrierten Routen live aus der laufenden App.

    Wird vom "Neu generieren"-Button verwendet, um den Endpunkt-Teil des Graphen
    mit dem echten aktuellen Stand der Anwendung abzugleichen.
    """
    live_endpoints = []
    for route in app.routes:
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        for method in sorted(methods):
            if method == "HEAD":
                continue
            live_endpoints.append({"method": method, "path": path, "name": getattr(route, "name", path)})
    return live_endpoints


def get_regenerated_graph(app: FastAPI) -> dict:
    """Mischt die live introspektierten Routen mit den kuratierten Service-/DB-Kanten.

    Bekannte Endpunkte (Methode+Pfad stimmt mit dem kuratierten Modell überein)
    behalten ihre Kanten. Neue, unbekannte Routen werden als eigenständige
    (kantenlose) Endpunkt-Knoten ergänzt; im kuratierten Modell fehlende Routen
    werden ausgeblendet, damit die Ansicht den echten App-Zustand widerspiegelt.
    """
    live = introspect_endpoints(app)
    live_keys = {(e["method"], e["path"]) for e in live}

    curated_endpoint_ids = {
        node_id for node_id, attrs in NODES.items() if attrs["type"] == "endpoint"
    }
    curated_keys = {
        node_id: (attrs["method"], attrs["path"])
        for node_id, attrs in NODES.items()
        if attrs["type"] == "endpoint"
    }

    kept_endpoint_ids = {
        node_id for node_id, key in curated_keys.items() if key in live_keys
    }

    nodes = [
        {"data": {"id": node_id, **attrs}}
        for node_id, attrs in NODES.items()
        if attrs["type"] != "endpoint" or node_id in kept_endpoint_ids
    ]

    # Unbekannte Live-Routen (im kuratierten Modell nicht erfasst) als Zusatzknoten anzeigen.
    known_live_keys = set(curated_keys.values())
    for e in live:
        key = (e["method"], e["path"])
        if key in known_live_keys or e["path"].startswith("/admin"):
            continue
        node_id = f"ep:auto:{e['method']}:{e['path']}"
        nodes.append(
            {
                "data": {
                    "id": node_id,
                    "label": f"{e['method']} {e['path']}",
                    "type": "endpoint",
                    "method": e["method"],
                    "path": e["path"],
                    "detail": "Live erkannt, kein kuratiertes Datenfluss-Wissen hinterlegt",
                }
            }
        )

    edges = [
        {"data": {"id": f"e{i}", "source": src, "target": tgt, "type": etype}}
        for i, (src, tgt, etype) in enumerate(EDGES)
        if src not in curated_endpoint_ids or src in kept_endpoint_ids
    ]

    return {"nodes": nodes, "edges": edges}
