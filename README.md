# Sport Dashboard API

Eine zentrale REST-API für Sport-Live- und Historikdaten. Aktuell unterstützte Sportarten:

- **Fußball (Bundesliga)** – Spielpläne, Tabelle, Aufstellungen, Spiel- und Spielerstatistiken, Ereignisse, Ausfälle (via WhoScored / `soccerdata`)
- **Formel 1** – Rennen & Fahrer (via OpenF1)
- **NFL** – Teams & Spiele (via Tank01 / RapidAPI)

> **Hinweis:** Web-Crawler sind im aktuellen Stand nicht enthalten und folgen in einer späteren Ausbaustufe.

---

## Features

- REST-API mit FastAPI – automatische Swagger UI (`/docs`) und ReDoc (`/redoc`)
- Datenbankanbindung via SQLAlchemy 2.0 + PostgreSQL (psycopg v3)
- Schemavorvalidierung mit Pydantic v2
- Datenbankmigrationen mit Alembic
- Admin-Endpunkte zum Auslösen von Datenimporten (geschützt per `X-API-Key`)
- Gesicherte Admin-Weboberfläche (`/admin`) mit Dashboard, Scheduler-Verwaltung und interaktivem Architektur-Graph
- Hintergrundaufgaben mit APScheduler
- WhoScored-Scraper (`soccerdata` + Chrome) mit normalisiertem 3NF-Fußballmodell (Spiele, Aufstellungen, Spielerstatistiken, Ereignisse, Ausfälle)
- Inkrementeller Fußball-Scheduler: Tages-Sync 04:00, Spieltag-Tick alle 3 min (Prematch T-45, Post-Match), stündlicher Catch-up – siehe [docs/scheduler.md](docs/scheduler.md)
- Admin-Importe als Hintergrund-Jobs (`/admin/import/football/...`, Status unter `/admin/jobs`) und CLI `python -m app.football_cli`
- Docker-Image mit Google Chrome (`Dockerfile`) für den Betrieb auf Render
- Render-Deployment (Docker) mit externer PostgreSQL-Datenbank, z. B. [Neon](https://neon.com) (`render.yaml`)
- Lokale Entwicklung mit separater Neon-DEV-Datenbank; Docker Compose ist eine optionale Alternative

---

## Tech-Stack

| Komponente         | Technologie                        |
|--------------------|------------------------------------|
| Sprache            | Python 3.14                        |
| Web-Framework      | FastAPI + Uvicorn                  |
| Datenbank          | PostgreSQL (psycopg v3)            |
| ORM / Migrationen  | SQLAlchemy 2.0 + Alembic           |
| Schemas            | Pydantic v2                        |
| HTTP-Client        | httpx                              |
| Fußball-Scraping   | soccerdata + seleniumbase + Google Chrome |
| Scheduler          | APScheduler                        |
| Container          | Docker (Image mit Chrome, Render)  |
| Admin-UI           | Jinja2 + Cytoscape.js (CDN)         |
| Tests              | pytest                             |

---

## Projektstruktur

```
Sport_Dashboard_API/
├── main.py                    # Anwendungs-Einstiegspunkt (FastAPI + Lifespan)
├── requirements.txt
├── alembic.ini
├── Dockerfile                 # Image mit Google Chrome (WhoScored-Scraper), Start: alembic + uvicorn
├── docker-compose.yml         # Optionale lokale DB: PostgreSQL + pgAdmin
├── render.yaml                # Render-Deployment-Blueprint (runtime: docker)
├── .env.example               # Vorlage für Umgebungsvariablen
├── app/
│   ├── config.py              # Einstellungen via Pydantic Settings
│   ├── logging_config.py
│   ├── football_cli.py        # CLI: Wettbewerbe, Saison-/Spielimport (WhoScored)
│   ├── api/
│   │   └── v1/                # FastAPI-Router (health, football, f1, nfl, admin)
│   ├── models/                # SQLAlchemy-Modelle
│   ├── schemas/                # Pydantic-Schemas (Football-Read-Schemas)
│   ├── services/               # Import-/Query-Services (Fetch → Normalize → Upsert)
│   │   └── datasources/        # Clients (OpenF1, WhoScored, Tank01)
│   ├── schedulers/             # APScheduler-Integration (F1- und Fußball-Jobs)
│   ├── web/                    # Admin-Weboberfläche (/admin): Router, Templates, Static
│   └── database/               # Session, Seed
├── migrations/                # Alembic-Migrationen
├── tests/                     # pytest-Tests
└── docs/                      # Dokumentation (Deutsch)
```

---

## Schnellstart

### 1. Virtuelle Umgebung aktivieren

```powershell
.venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Umgebungsvariablen einrichten

```powershell
copy .env.example .env
```

Nur ausführen, wenn noch keine `.env` vorhanden ist; eine bestehende Datei mit eigenen Werten nicht überschreiben.
Öffne `.env` und trage deine Werte ein – insbesondere den Connection-String der **Neon-DEV-Datenbank** in `DATABASE_URL`, `ADMIN_API_KEY` und die API-Keys für die Datenquellen (OpenF1 und WhoScored benötigen keinen Key; die `WHOSCORED_*`-Variablen steuern den Fußball-Scraper).
Voraussetzung für Fußballdaten: ein installierter **Google Chrome** (lokal; im Docker-Image ist er enthalten).
Details: [docs/datenquellen.md](docs/datenquellen.md)

### 3. DEV-Datenbank einrichten

Erstelle ein separates Neon-Projekt für DEV. Kopiere unter **Connect** die direkte PostgreSQL-URL ohne `psql` und äußere Anführungszeichen einschließlich der Verbindungsparameter in `DATABASE_URL`. Die URL enthält Zugangsdaten und darf nicht veröffentlicht werden. Für Neon ist eine Internetverbindung erforderlich.

Alternativ kannst du eine lokale Datenbank mit Docker verwenden: [docs/docker-anleitung.md](docs/docker-anleitung.md). Weitere Details zu Neon und zum lokalen Setup: [docs/entwicklung.md](docs/entwicklung.md).

### 4. Migrationen ausführen

Prüfe zuerst, dass `DATABASE_URL` auf DEV und nicht auf PROD zeigt:

```powershell
alembic upgrade head
```

### 5. Seed-Daten einspielen (optional)

```powershell
python -m app.database.seed
```

### 6. Fußball-Startdaten importieren (WhoScored, benötigt Chrome)

```powershell
python -m app.football_cli import-season --league GER-Bundesliga --season 2627
python -m app.football_cli import-season --league GER-Bundesliga --season 2526
```

Der Import lädt Spielplan und Details aller beendeten Spiele und dauert je Saison länger (eine Seite pro Spiel).
Mit `--no-details` wird nur der Spielplan geladen, mit `--max-matches N` die Anzahl der Detail-Abrufe begrenzt.
Details: [docs/entwicklung.md](docs/entwicklung.md), [docs/scheduler.md](docs/scheduler.md)

### 7. Anwendung starten

```powershell
uvicorn main:app --reload
```

API erreichbar unter: [http://localhost:8000](http://localhost:8000)
Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
Admin-Weboberfläche: [http://localhost:8000/admin](http://localhost:8000/admin) (Login mit `ADMIN_API_KEY`)

---

## API-Endpunkte (Überblick)

Alle Endpunkte haben den Präfix `/api/v1`.

| Methode | Pfad                              | Auth         | Beschreibung                          |
|---------|-----------------------------------|--------------|---------------------------------------|
| GET     | `/health`                         | Nein         | Health Check                          |
| GET     | `/football/competitions`          | Nein         | Fußball-Wettbewerbe inkl. Saisons     |
| GET     | `/football/{slug}/seasons`        | Nein         | Saisons eines Wettbewerbs             |
| GET     | `/football/{slug}/matches`        | Nein         | Spiele (Filter: season, team_id, status, date_from, date_to) |
| GET     | `/football/{slug}/standings`      | Nein         | Tabelle (aus Ergebnissen berechnet)   |
| GET     | `/football/{slug}/teams`          | Nein         | Teams einer Saison                    |
| GET     | `/football/{slug}/missing-players`| Nein         | Ausfälle aller Teams einer Saison     |
| GET     | `/football/matches/{id}`          | Nein         | Spieldetails (Ereignisse, Formationen)|
| GET     | `/football/matches/{id}/lineups`  | Nein         | Aufstellungen und Bank                |
| GET     | `/football/matches/{id}/stats`    | Nein         | Team- und Spielerstatistiken          |
| GET     | `/football/teams/{id}`            | Nein         | Team inkl. Land                       |
| GET     | `/football/teams/{id}/matches`    | Nein         | Spiele eines Teams                    |
| GET     | `/football/teams/{id}/missing-players` | Nein    | Ausfälle eines Teams                  |
| GET     | `/f1/races`                       | Nein         | F1-Rennen                             |
| GET     | `/f1/drivers`                     | Nein         | F1-Fahrer                             |
| GET     | `/f1/races/{race_id}/sessions`    | Nein         | Sessions eines Rennens                |
| GET     | `/f1/sessions/{session_id}/results` | Nein       | Ergebnisse einer Session              |
| GET     | `/f1/standings/drivers`, `/f1/standings/constructors` | Nein | F1-Wertungen            |
| GET     | `/nfl/teams`                      | Nein         | NFL-Teams                             |
| GET     | `/nfl/games`                      | Nein         | NFL-Spiele                            |
| GET     | `/nfl/standings`                  | Nein         | NFL-Tabelle                           |
| POST    | `/admin/import/football/season`   | `X-API-Key`  | WhoScored-Saisonimport (Hintergrund-Job, 202) |
| POST    | `/admin/import/football/match/{ws_match_id}` | `X-API-Key` | Einzelnes Spiel synchronisieren (Hintergrund-Job, 202) |
| GET     | `/admin/jobs`, `/admin/jobs/{id}` | `X-API-Key`  | Status der Hintergrund-Jobs           |
| POST    | `/admin/import/f1/races`          | `X-API-Key`  | F1-Rennen importieren                 |
| POST    | `/admin/import/f1/drivers`        | `X-API-Key`  | F1-Fahrer importieren                 |
| POST    | `/admin/import/f1/sessions`, `/admin/import/f1/session-results`, `/admin/import/f1/standings` | `X-API-Key` | F1-Sessions, Ergebnisse, Wertungen importieren |
| POST    | `/admin/import/nfl/teams`         | `X-API-Key`  | NFL-Teams importieren                 |
| POST    | `/admin/import/nfl/games-new`     | `X-API-Key`  | NFL-Spiele importieren                |
| POST    | `/admin/import/nfl/standings`     | `X-API-Key`  | NFL-Tabelle importieren               |

Vollständige API-Referenz: [docs/api.md](docs/api.md)

---

## Admin-Weboberfläche

Unter `/admin` steht eine gesicherte, browserbasierte Oberfläche zur Verfügung:

- **Dashboard** – Kennzahlen und Schnellaktionen zum Auslösen von Datenimporten
- **Scheduler** – Jobs ansehen, pausieren/fortsetzen, sofort ausführen, Ausführungshistorie
- **Architektur** – interaktiver Graph: Endpunkt → Service → Datenquelle/DB-Tabelle → Scheduler-Job
- **Endpunkte** – tabellarische Referenz aller Endpunkte mit Datenfluss

Login unter `/admin/login` mit dem `ADMIN_API_KEY`; danach übernimmt ein signiertes Session-Cookie
(`SESSION_SECRET`) die Authentifizierung im Browser. Die `/admin/api/...`-Endpunkte akzeptieren
zusätzlich weiterhin den `X-API-Key`-Header.

---

## Authentifizierung

Admin-Endpunkte erfordern den HTTP-Header:

```
X-API-Key: <dein ADMIN_API_KEY>
```

Der Wert wird in der Umgebungsvariable `ADMIN_API_KEY` definiert. Öffentliche GET-Endpunkte benötigen keinen Key.

Die Admin-Weboberfläche (`/admin`) nutzt zusätzlich ein signiertes Session-Cookie nach dem Login
(Signierschlüssel: `SESSION_SECRET`).

---

## Dokumentation

| Dokument                                          | Inhalt                                      |
|---------------------------------------------------|---------------------------------------------|
| [docs/entwicklung.md](docs/entwicklung.md)        | Lokales Setup, Tests, neue Migrationen      |
| [docs/docker-anleitung.md](docs/docker-anleitung.md) | Optionale lokale Docker-Datenbank        |
| [docs/api.md](docs/api.md)                        | Vollständige API-Referenz                   |
| [docs/datenquellen.md](docs/datenquellen.md)      | OpenF1, WhoScored, Tank01 – Keys & Setup    |
| [docs/scheduler.md](docs/scheduler.md)            | Hintergrundjobs, Fußball-Scheduler          |
| [docs/deployment.md](docs/deployment.md)          | Deployment auf Render (Docker) mit Neon     |

---

## Tests

```powershell
pytest -q
```
