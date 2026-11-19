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
    "ds:tank01": {"label": "Tank01 NFL API", "type": "datasource", "detail": "RapidAPI – NFL-Teams/Spiele/Standings"},
    "ds:whoscored": {"label": "WhoScored (soccerdata/Chrome)", "type": "datasource", "detail": "whoscored.com – Fußballdaten (Spielplan, Aufstellungen, Statistiken, Ausfälle); per soccerdata + Chrome gescrapt, langsam (~10 s/Seite)"},

    # ── DB-Tabellen ──────────────────────────────────────────────────────────
    "tbl:competitions": {"label": "competitions", "type": "table", "detail": "app/models/competition.py"},
    "tbl:teams": {"label": "teams", "type": "table", "detail": "app/models/team.py"},
    "tbl:matches": {"label": "matches", "type": "table", "detail": "app/models/match.py"},
    "tbl:players": {"label": "players", "type": "table", "detail": "app/models/player.py"},
    "tbl:regions": {"label": "regions", "type": "table", "detail": "app/models/region.py"},
    "tbl:countries": {"label": "countries", "type": "table", "detail": "app/models/country.py"},
    "tbl:seasons": {"label": "seasons", "type": "table", "detail": "app/models/season.py"},
    "tbl:stages": {"label": "stages", "type": "table", "detail": "app/models/season.py"},
    "tbl:venues": {"label": "venues", "type": "table", "detail": "app/models/venue.py"},
    "tbl:referees": {"label": "referees", "type": "table", "detail": "app/models/referee.py"},
    "tbl:managers": {"label": "managers", "type": "table", "detail": "app/models/manager.py"},
    "tbl:match_teams": {"label": "match_teams", "type": "table", "detail": "app/models/match.py – Trainer/Durchschnittsalter je Team und Spiel"},
    "tbl:appearances": {"label": "appearances", "type": "table", "detail": "app/models/appearance.py"},
    "tbl:formations": {"label": "formations", "type": "table", "detail": "app/models/formation.py"},
    "tbl:formation_positions": {"label": "formation_positions", "type": "table", "detail": "app/models/formation.py"},
    "tbl:stat_types": {"label": "stat_types", "type": "table", "detail": "app/models/stat.py"},
    "tbl:team_match_stats": {"label": "team_match_stats", "type": "table", "detail": "app/models/stat.py"},
    "tbl:player_match_stats": {"label": "player_match_stats", "type": "table", "detail": "app/models/stat.py"},
    "tbl:match_incidents": {"label": "match_incidents", "type": "table", "detail": "app/models/match_incident.py"},
    "tbl:missing_players": {"label": "missing_players", "type": "table", "detail": "app/models/missing_player.py"},
    "tbl:match_sync_state": {"label": "match_sync_state", "type": "table", "detail": "app/models/match_sync_state.py"},
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
    "svc:import_nfl_teams": {"label": "import_nfl_teams()", "type": "service", "detail": "app/services/nfl_service.py"},
    "svc:import_nfl_games_new": {"label": "import_nfl_games_new()", "type": "service", "detail": "app/services/nfl_service.py – nfl_games-Tabelle"},
    "svc:import_nfl_standings": {"label": "import_nfl_standings()", "type": "service", "detail": "app/services/nfl_service.py"},
    "svc:import_season": {"label": "import_season()", "type": "service", "detail": "app/services/football_service.py – Saison-Import (Spielplan + optional Spieldetails)"},
    "svc:sync_fixtures": {"label": "sync_fixtures()", "type": "service", "detail": "app/services/football_service.py – Spielplan/Ergebnisse"},
    "svc:sync_match_details": {"label": "sync_match_details()", "type": "service", "detail": "app/services/football_service.py – Aufstellungen, Statistiken, Ereignisse"},
    "svc:sync_missing_players": {"label": "sync_missing_players()", "type": "service", "detail": "app/services/football_service.py – Ausfälle aus der Spielvorschau"},
    "svc:compute_standings": {"label": "compute_standings()", "type": "service", "detail": "app/services/football_queries.py – Tabelle aus abgeschlossenen Spielen berechnet (nicht gespeichert)"},

    # ── Scheduler-Jobs ───────────────────────────────────────────────────────
    "job:nightly_session_status_update": {"label": "nightly_session_status_update", "type": "job", "detail": "Cron täglich 03:00 – RaceSession-Status upcoming→completed"},
    "job:hourly_f1_data_fetch": {"label": "hourly_f1_data_fetch", "type": "job", "detail": "Interval 1h – lädt fehlende F1-Session-Ergebnisse nach, aktualisiert Standings"},
    "job:football_daily_sync": {"label": "football_daily_sync", "type": "job", "detail": "Cron täglich 04:00 – WhoScored-Spielpläne (inkrementell, montags/Bootstrap komplett) + finaler Detail-Nachlauf"},
    "job:football_matchday_tick": {"label": "football_matchday_tick", "type": "job", "detail": "Interval 3 min – Prematch (T-45), Aufstellungs-Retry (T-20), Post-Match-Polling; entscheidet aus In-Memory-Cache"},
    "job:football_hourly_catchup": {"label": "football_hourly_catchup", "type": "job", "detail": "Cron stündlich :17 – fehlende Match-Details nachladen, überfällige Spielstatus korrigieren"},
    "job:football_bootstrap": {"label": "football_bootstrap", "type": "job", "detail": "Einmalig ~60 s nach Start – Erst-Import leerer aktueller Saisons"},

    # ── Endpunkte ────────────────────────────────────────────────────────────
    "ep:GET:/api/v1/health": {"label": "GET /health", "type": "endpoint", "method": "GET", "path": "/api/v1/health"},

    "ep:GET:/api/v1/f1/races": {"label": "GET /f1/races", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/races"},
    "ep:GET:/api/v1/f1/drivers": {"label": "GET /f1/drivers", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/drivers"},
    "ep:GET:/api/v1/f1/races/{race_id}/sessions": {"label": "GET /f1/races/{id}/sessions", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/races/{race_id}/sessions"},
    "ep:GET:/api/v1/f1/sessions/{session_id}/results": {"label": "GET /f1/sessions/{id}/results", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/sessions/{session_id}/results"},
    "ep:GET:/api/v1/f1/standings/drivers": {"label": "GET /f1/standings/drivers", "type": "endpoint", "method": "GET", "path": "/api/v1/f1/standings/drivers"},

    "ep:GET:/api/v1/nfl/teams": {"label": "GET /nfl/teams", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/teams"},
    "ep:GET:/api/v1/nfl/games": {"label": "GET /nfl/games", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/games"},
    "ep:GET:/api/v1/nfl/standings": {"label": "GET /nfl/standings", "type": "endpoint", "method": "GET", "path": "/api/v1/nfl/standings"},

    "ep:POST:/api/v1/admin/import/f1/races": {"label": "POST /admin/import/f1/races", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/races"},
    "ep:POST:/api/v1/admin/import/f1/drivers": {"label": "POST /admin/import/f1/drivers", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/drivers"},
    "ep:POST:/api/v1/admin/import/f1/sessions": {"label": "POST /admin/import/f1/sessions", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/sessions"},
    "ep:POST:/api/v1/admin/import/f1/session-results": {"label": "POST /admin/import/f1/session-results", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/session-results"},
    "ep:POST:/api/v1/admin/import/f1/standings": {"label": "POST /admin/import/f1/standings", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/f1/standings"},
    "ep:POST:/api/v1/admin/import/nfl/teams": {"label": "POST /admin/import/nfl/teams", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/teams"},
    "ep:POST:/api/v1/admin/import/nfl/games-new": {"label": "POST /admin/import/nfl/games-new", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/games-new"},
    "ep:POST:/api/v1/admin/import/nfl/standings": {"label": "POST /admin/import/nfl/standings", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/nfl/standings"},

    "ep:GET:/api/v1/football/competitions": {"label": "GET /football/competitions", "type": "endpoint", "method": "GET", "path": "/api/v1/football/competitions"},
    "ep:GET:/api/v1/football/{slug}/seasons": {"label": "GET /football/{slug}/seasons", "type": "endpoint", "method": "GET", "path": "/api/v1/football/{slug}/seasons"},
    "ep:GET:/api/v1/football/{slug}/matches": {"label": "GET /football/{slug}/matches", "type": "endpoint", "method": "GET", "path": "/api/v1/football/{slug}/matches"},
    "ep:GET:/api/v1/football/{slug}/standings": {"label": "GET /football/{slug}/standings", "type": "endpoint", "method": "GET", "path": "/api/v1/football/{slug}/standings"},
    "ep:GET:/api/v1/football/{slug}/teams": {"label": "GET /football/{slug}/teams", "type": "endpoint", "method": "GET", "path": "/api/v1/football/{slug}/teams"},
    "ep:GET:/api/v1/football/{slug}/missing-players": {"label": "GET /football/{slug}/missing-players", "type": "endpoint", "method": "GET", "path": "/api/v1/football/{slug}/missing-players"},
    "ep:GET:/api/v1/football/matches/{match_id}": {"label": "GET /football/matches/{id}", "type": "endpoint", "method": "GET", "path": "/api/v1/football/matches/{match_id}"},
    "ep:GET:/api/v1/football/matches/{match_id}/lineups": {"label": "GET /football/matches/{id}/lineups", "type": "endpoint", "method": "GET", "path": "/api/v1/football/matches/{match_id}/lineups"},
    "ep:GET:/api/v1/football/matches/{match_id}/stats": {"label": "GET /football/matches/{id}/stats", "type": "endpoint", "method": "GET", "path": "/api/v1/football/matches/{match_id}/stats"},
    "ep:GET:/api/v1/football/teams/{team_id}": {"label": "GET /football/teams/{id}", "type": "endpoint", "method": "GET", "path": "/api/v1/football/teams/{team_id}"},
    "ep:GET:/api/v1/football/teams/{team_id}/matches": {"label": "GET /football/teams/{id}/matches", "type": "endpoint", "method": "GET", "path": "/api/v1/football/teams/{team_id}/matches"},
    "ep:GET:/api/v1/football/teams/{team_id}/missing-players": {"label": "GET /football/teams/{id}/missing-players", "type": "endpoint", "method": "GET", "path": "/api/v1/football/teams/{team_id}/missing-players"},

    "ep:POST:/api/v1/admin/import/football/season": {"label": "POST /admin/import/football/season", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/football/season", "detail": "Startet einen Hintergrund-Job (202), Status über /admin/jobs"},
    "ep:POST:/api/v1/admin/import/football/match/{ws_match_id}": {"label": "POST /admin/import/football/match/{id}", "type": "endpoint", "method": "POST", "path": "/api/v1/admin/import/football/match/{ws_match_id}", "detail": "Startet einen Hintergrund-Job (202), Status über /admin/jobs"},
    "ep:GET:/api/v1/admin/jobs": {"label": "GET /admin/jobs", "type": "endpoint", "method": "GET", "path": "/api/v1/admin/jobs"},
    "ep:GET:/api/v1/admin/jobs/{job_id}": {"label": "GET /admin/jobs/{id}", "type": "endpoint", "method": "GET", "path": "/api/v1/admin/jobs/{job_id}"},
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

    ("ep:GET:/api/v1/nfl/teams", "svc:import_nfl_teams", "calls"),
    ("ep:GET:/api/v1/nfl/games", "svc:import_nfl_games_new", "calls"),
    ("ep:GET:/api/v1/nfl/standings", "svc:import_nfl_standings", "calls"),

    # Admin-Endpunkte lösen die gleichen Services aus (erzwungener Re-Import)
    ("ep:POST:/api/v1/admin/import/f1/races", "svc:import_f1_races", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/drivers", "svc:import_f1_drivers", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/sessions", "svc:import_f1_sessions", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/session-results", "svc:import_f1_session_results", "calls"),
    ("ep:POST:/api/v1/admin/import/f1/standings", "svc:import_f1_standings", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/teams", "svc:import_nfl_teams", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/games-new", "svc:import_nfl_games_new", "calls"),
    ("ep:POST:/api/v1/admin/import/nfl/standings", "svc:import_nfl_standings", "calls"),

    # Services -> externe Datenquellen
    ("svc:import_f1_races", "ds:openf1", "fetches"),
    ("svc:import_f1_drivers", "ds:openf1", "fetches"),
    ("svc:import_f1_sessions", "ds:openf1", "fetches"),
    ("svc:import_f1_sessions_for_race", "ds:openf1", "fetches"),
    ("svc:import_f1_session_results", "ds:openf1", "fetches"),
    ("svc:import_f1_standings", "ds:openf1", "fetches"),
    ("svc:import_nfl_teams", "ds:tank01", "fetches"),
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

    ("svc:import_nfl_teams", "tbl:nfl_teams", "writes"),
    ("svc:import_nfl_games_new", "tbl:nfl_games", "writes"),
    ("svc:import_nfl_games_new", "tbl:nfl_teams", "reads"),
    ("svc:import_nfl_standings", "tbl:nfl_standings", "writes"),
    ("svc:import_nfl_standings", "tbl:nfl_teams", "reads"),

    # Fußball (WhoScored): öffentliche Lese-Endpunkte (kein Auto-Import) -> Tabellen
    ("ep:GET:/api/v1/football/competitions", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/competitions", "tbl:regions", "reads"),
    ("ep:GET:/api/v1/football/competitions", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/seasons", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/{slug}/seasons", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/matches", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/{slug}/matches", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/matches", "tbl:stages", "reads"),
    ("ep:GET:/api/v1/football/{slug}/matches", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/{slug}/matches", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/{slug}/standings", "svc:compute_standings", "calls"),
    ("ep:GET:/api/v1/football/{slug}/standings", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/{slug}/standings", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/teams", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/{slug}/teams", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/teams", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/{slug}/teams", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/{slug}/teams", "tbl:countries", "reads"),
    ("ep:GET:/api/v1/football/{slug}/missing-players", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/{slug}/missing-players", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/{slug}/missing-players", "tbl:missing_players", "reads"),
    ("ep:GET:/api/v1/football/{slug}/missing-players", "tbl:players", "reads"),
    ("ep:GET:/api/v1/football/{slug}/missing-players", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:venues", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:referees", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:match_teams", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:managers", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:formations", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:formation_positions", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:match_incidents", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:match_sync_state", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}", "tbl:players", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/lineups", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/lineups", "tbl:appearances", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/lineups", "tbl:players", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/stats", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/stats", "tbl:team_match_stats", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/stats", "tbl:player_match_stats", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/stats", "tbl:stat_types", "reads"),
    ("ep:GET:/api/v1/football/matches/{match_id}/stats", "tbl:appearances", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}", "tbl:countries", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/matches", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/matches", "tbl:matches", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/matches", "tbl:competitions", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/matches", "tbl:seasons", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/missing-players", "tbl:teams", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/missing-players", "tbl:missing_players", "reads"),
    ("ep:GET:/api/v1/football/teams/{team_id}/missing-players", "tbl:players", "reads"),

    # Fußball: Admin-Endpunkte (Hintergrund-Jobs) -> Services
    ("ep:POST:/api/v1/admin/import/football/season", "svc:import_season", "calls"),
    ("ep:POST:/api/v1/admin/import/football/match/{ws_match_id}", "svc:sync_match_details", "calls"),
    ("ep:POST:/api/v1/admin/import/football/match/{ws_match_id}", "svc:sync_missing_players", "calls"),

    # Fußball: Service-Aufrufe untereinander
    ("svc:import_season", "svc:sync_fixtures", "calls"),
    ("svc:import_season", "svc:sync_match_details", "calls"),
    ("svc:import_season", "svc:sync_missing_players", "calls"),

    # Fußball: Services -> WhoScored
    ("svc:sync_fixtures", "ds:whoscored", "fetches"),
    ("svc:sync_match_details", "ds:whoscored", "fetches"),
    ("svc:sync_missing_players", "ds:whoscored", "fetches"),

    # Fußball: Services <-> DB-Tabellen
    ("svc:sync_fixtures", "tbl:regions", "writes"),
    ("svc:sync_fixtures", "tbl:competitions", "writes"),
    ("svc:sync_fixtures", "tbl:seasons", "writes"),
    ("svc:sync_fixtures", "tbl:stages", "writes"),
    ("svc:sync_fixtures", "tbl:countries", "writes"),
    ("svc:sync_fixtures", "tbl:teams", "writes"),
    ("svc:sync_fixtures", "tbl:matches", "writes"),
    ("svc:sync_fixtures", "tbl:match_sync_state", "writes"),
    ("svc:sync_match_details", "tbl:matches", "writes"),
    ("svc:sync_match_details", "tbl:venues", "writes"),
    ("svc:sync_match_details", "tbl:referees", "writes"),
    ("svc:sync_match_details", "tbl:managers", "writes"),
    ("svc:sync_match_details", "tbl:match_teams", "writes"),
    ("svc:sync_match_details", "tbl:players", "writes"),
    ("svc:sync_match_details", "tbl:appearances", "writes"),
    ("svc:sync_match_details", "tbl:formations", "writes"),
    ("svc:sync_match_details", "tbl:formation_positions", "writes"),
    ("svc:sync_match_details", "tbl:stat_types", "writes"),
    ("svc:sync_match_details", "tbl:team_match_stats", "writes"),
    ("svc:sync_match_details", "tbl:player_match_stats", "writes"),
    ("svc:sync_match_details", "tbl:match_incidents", "writes"),
    ("svc:sync_match_details", "tbl:match_sync_state", "writes"),
    ("svc:sync_match_details", "tbl:teams", "reads"),
    ("svc:sync_missing_players", "tbl:missing_players", "writes"),
    ("svc:sync_missing_players", "tbl:players", "writes"),
    ("svc:sync_missing_players", "tbl:match_sync_state", "writes"),
    ("svc:sync_missing_players", "tbl:matches", "reads"),
    ("svc:sync_missing_players", "tbl:teams", "reads"),
    ("svc:compute_standings", "tbl:stages", "reads"),
    ("svc:compute_standings", "tbl:matches", "reads"),
    ("svc:compute_standings", "tbl:teams", "reads"),

    # Scheduler-Jobs -> Services / Tabellen
    ("job:nightly_session_status_update", "tbl:race_sessions", "writes"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_session_results", "triggers"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_drivers", "triggers"),
    ("job:hourly_f1_data_fetch", "svc:import_f1_standings", "triggers"),
    ("job:football_daily_sync", "svc:sync_fixtures", "triggers"),
    ("job:football_daily_sync", "svc:sync_match_details", "triggers"),
    ("job:football_matchday_tick", "svc:sync_fixtures", "triggers"),
    ("job:football_matchday_tick", "svc:sync_match_details", "triggers"),
    ("job:football_matchday_tick", "svc:sync_missing_players", "triggers"),
    ("job:football_hourly_catchup", "svc:sync_fixtures", "triggers"),
    ("job:football_hourly_catchup", "svc:sync_match_details", "triggers"),
    ("job:football_bootstrap", "svc:sync_fixtures", "triggers"),
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
