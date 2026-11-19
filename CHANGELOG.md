# Changelog

Alle wesentlichen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

## [0.3.0] - 2026-11-19

### Hinzugefügt

- **WhoScored als Fußball-Datenquelle** (`app/services/datasources/whoscored.py`, `whoscored_parsers.py`): Scraping über
  `soccerdata` + seleniumbase/Chrome (kein API-Key nötig); neue Abhängigkeit `soccerdata`
- Wettbewerbs-Registry `app/services/football_competitions.py` (aktuell `GER-Bundesliga`), konfigurierbar über
  `WHOSCORED_LEAGUES`
- Neues normalisiertes 3NF-Fußballmodell mit Alembic-Migration `a3f1c9d27b4e`: `regions`, `countries`, `seasons`,
  `stages`, `venues`, `referees`, `managers`, erweiterte `competitions`/`teams`/`players`/`matches`, `match_teams`,
  `appearances`, `formations`, `formation_positions`, `stat_types`, `team_match_stats`, `player_match_stats`,
  `match_incidents`, `missing_players`, `match_sync_state`
- Schreib-Service `football_service.py` (Spielpläne, Match-Details mit Aufstellungen/Statistiken/Ereignissen/Bewertungen,
  Ausfälle aus der Spielvorschau, Saisonimport) und Lese-Service `football_queries.py` (Tabelle wird aus den Ergebnissen
  berechnet)
- Neue öffentliche Fußball-Endpunkte unter `/api/v1/football/...`: `competitions`, `{slug}/seasons`, `{slug}/matches`,
  `{slug}/standings`, `{slug}/teams`, `{slug}/missing-players`, `matches/{id}`, `matches/{id}/lineups`,
  `matches/{id}/stats`, `teams/{id}`, `teams/{id}/matches`, `teams/{id}/missing-players`
- Admin-Endpunkte als Hintergrund-Jobs (HTTP 202): `POST /admin/import/football/season`,
  `POST /admin/import/football/match/{ws_match_id}`, Status über `GET /admin/jobs` und `/admin/jobs/{id}`
  (`background_jobs.py`, `football_jobs.py`); passende Aktionen in der Admin-Weboberfläche
- CLI `python -m app.football_cli` (`competitions`, `import-season`, `sync-match`)
- Inkrementeller Fußball-Scheduler (`app/schedulers/football_jobs.py`, Doku: `docs/scheduler.md`):
  `football_daily_sync` (täglich 04:00), `football_matchday_tick` (alle 3 min, entscheidet aus einem In-Memory-Cache ohne
  DB-Zugriff; Prematch T-45, zweiter Aufstellungsversuch, Post-Match-Polling), `football_hourly_catchup` (Minute 17) und
  `football_bootstrap` (Erst-Import ~60 s nach Start); ein Browser pro Prozess, PostgreSQL-Advisory-Lock pro Datenbank
- Neue Umgebungsvariablen: `WHOSCORED_ENABLED`, `WHOSCORED_LEAGUES`, `WHOSCORED_HEADLESS`, `WHOSCORED_BROWSER_PATH`,
  `WHOSCORED_DATA_DIR`, `WHOSCORED_LOCK_TIMEOUT_SECONDS`
- `Dockerfile` (Python 3.14 + Google Chrome, tini, nicht privilegierter Benutzer) und `.dockerignore`
- Tests und Fixtures für Parser, Service, API, Admin-Jobs und Scheduler (`tests/test_whoscored.py`,
  `test_football_*.py`, `tests/fixtures/`)

### Geändert

- Datenquelle für Fußball: **API-Football → WhoScored**; Seed-Daten, Admin-Dashboard, Architektur-Graph und
  Endpunkt-Metadaten an das neue Modell angepasst
- **Migration:** `alembic upgrade head` löscht die alten Fußballdaten (`competitions`, `teams`, `matches`, `players`,
  `standings`, `injuries` des API-Football-Stacks) und legt die neuen Tabellen an; Daten danach per Import neu laden
  (`python -m app.football_cli import-season --league GER-Bundesliga --season 2627`, ebenso `2526`)
- `GET /api/v1/nfl/games` liefert immer `nfl_games` (ohne `season` das aktuelle Jahr)
- Render-Deployment läuft jetzt mit `runtime: docker` (`render.yaml`); der Start-Befehl im `Dockerfile` führt
  `alembic upgrade head` und danach uvicorn (ein Worker) aus
- `FastAPI`-Version 0.3.0, Beschreibung nennt Fußball (WhoScored)
- Dokumentation aktualisiert (`api.md`, `datenquellen.md`, `deployment.md`, `entwicklung.md`, `docker-anleitung.md`,
  neu: `scheduler.md`), `.env.example` und `.gitignore` (`downloaded_files/`)

### Entfernt

- API-Football-Client (`api_football.py`) und die Umgebungsvariablen `API_FOOTBALL_KEY`/`API_FOOTBALL_BASE_URL`
- Endpunkte `/api/v1/bundesliga/*` (ersetzt durch `/api/v1/football/{slug}/...`)
- Legacy-NFL-Pfad: `import_nfl_games`, `POST /admin/import/nfl/games` und der Legacy-Zweig von `GET /nfl/games`
  (matches-Tabelle)
- Alter Match-Monitor (`schedule_match_monitor`, `_check_match_finished`)
- Alte Fußball-Modelle/-Schemas (`Standing`, `Injury`, `schemas/{competition,team,match,player,standing,injury}.py`);
  Tabelle und Ausfälle werden nun berechnet bzw. in `missing_players` geführt

## [0.2.0] - 2026-09-27

### Hinzugefügt

- Gesicherte Admin-Weboberfläche unter `/admin` (Jinja2 + Cytoscape.js), Login per `ADMIN_API_KEY`
  mit signiertem Session-Cookie (`SESSION_SECRET`); `require_admin` akzeptiert nun sowohl den
  `X-API-Key`-Header als auch das Session-Cookie
- `/admin` Dashboard mit Live-Kennzahlen (DB-Zeilenanzahl, Scheduler-Status) und Schnellaktions-
  Buttons zum direkten Auslösen aller bestehenden Import-Services
- `/admin/schedulers`: Scheduler-Jobs ansehen, pausieren/fortsetzen, sofort ausführen ("Run now")
  sowie eine In-Memory-Ausführungshistorie (APScheduler-Event-Listener)
- `/admin/architecture`: interaktiver Abhängigkeitsgraph (Endpunkt → Service → Datenquelle/
  DB-Tabelle → Scheduler-Job) aus einem kuratierten Metadaten-Modul, mit "Neu generieren"-Button
  zur Live-Introspektion der registrierten Routen
- `/admin/endpoints`: filterbare tabellarische Referenz aller Endpunkte mit Datenfluss
- Neue Scheduler-Verwaltungsfunktionen (`list_jobs`, `pause_job`, `resume_job`, `run_job_now`,
  `get_job_history`, `scheduler_status`) in `app/schedulers/scheduler.py`
- Swagger-Doku-Link (`/docs`) direkt in der Admin-Navigation

## [0.1.0] - 2026-07-23

### Hinzugefügt

- Projekt-Fundament: Struktur, Konfiguration, Datenbank-Session, Logging
- SQLAlchemy-2.0-Modelle: Competition, Team, Match, Driver, Race, NflTeam
- Pydantic-v2-Schemas (Base/Create/Read) für alle Entitäten
- FastAPI-Grundgerüst: Health-Endpoint `/api/v1/health`, Admin-Auth via `X-API-Key`, zentraler v1-Router
- Synchrone Datenquellen-Clients für OpenF1, API-Football und Tank01 (httpx)
- Alembic-Setup mit Initial-Migration für alle 6 Tabellen
- Import-Services (Fetch → Normalize → Upsert) für Bundesliga, Formel 1 und NFL
- Minimale Seed-Daten inkl. CLI (`python -m app.database.seed`)
- REST-Endpunkte für Bundesliga, F1, NFL sowie Admin-Import-Endpunkte
- APScheduler-Integration mit dynamischem Match-Monitor und Lifespan-Anbindung
- Deployment-Konfiguration: `docker-compose.yml` (Postgres + pgAdmin) und `render.yaml`; DB-URL-Normalisierung für Render
- Deutschsprachige Dokumentation unter `docs/` und README
