# Changelog

Alle wesentlichen Änderungen an diesem Projekt werden in dieser Datei dokumentiert.

Das Format basiert auf [Keep a Changelog](https://keepachangelog.com/de/1.0.0/).

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
