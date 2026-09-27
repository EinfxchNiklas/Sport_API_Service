# Lokales Setup & Entwicklung

Diese Anleitung beschreibt, wie du die Sport Dashboard API lokal zum Laufen bringst.

---

## Voraussetzungen

- Python 3.14 (oder kompatibel)
- Docker Desktop (für die lokale Datenbank) → siehe [docker-anleitung.md](docker-anleitung.md)
- Git

---

## Schritt 1: Virtuelle Umgebung aktivieren

Das Projekt verwendet eine virtuelle Python-Umgebung (`.venv`). Aktiviere sie in der PowerShell:

```powershell
.venv\Scripts\activate
```

Nach der Aktivierung siehst du `(.venv)` am Anfang der Eingabeaufforderung.

Falls die `.venv` noch nicht existiert, erstelle sie zuerst:

```powershell
python -m venv .venv
.venv\Scripts\activate
```

---

## Schritt 2: Abhängigkeiten installieren

```powershell
pip install -r requirements.txt
```

---

## Schritt 3: Umgebungsvariablen konfigurieren

Kopiere die Beispieldatei und trage deine Werte ein:

```powershell
copy .env.example .env
```

Öffne `.env` in einem Texteditor und fülle alle Felder aus. Eine Übersicht der Variablen:

| Variable               | Beschreibung                                                   |
|------------------------|----------------------------------------------------------------|
| `APP_ENV`              | Umgebung: `development` oder `production`                      |
| `DATABASE_URL`         | PostgreSQL-Verbindungs-URL (z. B. `postgresql+psycopg://sport:sport@localhost:5432/sportdb`) |
| `ADMIN_API_KEY`        | Geheimer Schlüssel für Admin-Endpunkte (beliebiger sicherer Wert) |
| `SESSION_SECRET`       | Signier-Schlüssel für das Admin-UI-Session-Cookie (`/admin`), beliebiger sicherer Wert |
| `LOG_LEVEL`            | Log-Level: `DEBUG`, `INFO`, `WARNING`, `ERROR`                 |
| `ENABLE_SCHEDULER`     | Scheduler aktivieren: `true` oder `false`                      |
| `OPENF1_BASE_URL`      | Basis-URL der OpenF1-API (Standard: `https://api.openf1.org/v1`) |
| `API_FOOTBALL_KEY`     | API-Schlüssel für api-football.com                             |
| `API_FOOTBALL_BASE_URL`| Basis-URL der API-Football-API                                 |
| `TANK01_KEY`           | RapidAPI-Schlüssel für Tank01 (NFL)                            |
| `TANK01_HOST`          | RapidAPI-Host für Tank01                                       |
| `TIMEZONE`             | Zeitzone, z. B. `Europe/Berlin`                                |

> **Hinweis zu API-Keys:** Details zu den Datenquellen und wo du die Keys bekommst, findest du in [datenquellen.md](datenquellen.md).

---

## Schritt 4: Datenbank starten

Starte die PostgreSQL-Datenbank via Docker:

```powershell
docker compose up -d
```

Detaillierte Anleitung zur Docker-Einrichtung (inkl. Installation): [docker-anleitung.md](docker-anleitung.md)

---

## Schritt 5: Datenbankmigrationen ausführen

Erstelle alle Tabellen in der Datenbank:

```powershell
alembic upgrade head
```

---

## Schritt 6: Seed-Daten einspielen (optional)

Fülle die Datenbank mit minimalen Beispieldaten:

```powershell
python -m app.database.seed
```

---

## Schritt 7: Anwendung starten

```powershell
uvicorn main:app --reload
```

Die API ist nun unter [http://localhost:8000](http://localhost:8000) erreichbar.

- **Swagger UI** (interaktive API-Doku): [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc** (alternative Doku): [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Tests ausführen

```powershell
pytest -q
```

Alle Tests befinden sich im Verzeichnis `tests/`.

---

## Neue Datenbankmigration erstellen

Wenn du ein Datenbankmodell geändert hast, erstelle eine neue Migration:

```powershell
alembic revision --autogenerate -m "Kurze Beschreibung der Änderung"
```

Prüfe die generierte Migrations-Datei unter `migrations/versions/` auf Korrektheit, bevor du sie anwendest:

```powershell
alembic upgrade head
```

---

## Tagesstart & Feierabend

### Feierabend – Alles sauber beenden

1. **FastAPI-Server stoppen** – im Terminal mit `Strg+C`
2. **Docker-Container stoppen** (Daten bleiben erhalten):
   ```powershell
   docker compose stop
   ```

Der Scheduler läuft im selben Prozess wie FastAPI und stoppt automatisch mit dem Server.

> `docker compose stop` hält die Container an, löscht sie aber nicht. Die Datenbank-Daten im Volume `postgres_data` bleiben vollständig erhalten.

---

### Nächster Tag – Wieder loslegen

1. **Docker-Desktop starten:**

2. **Docker-Container starten:**
   ```powershell
   docker compose up -d
   ```
3. **Virtuelle Umgebung aktivieren** (falls noch nicht aktiv):
   ```powershell
   .venv\Scripts\activate
   ```
4. **FastAPI-Server starten:**
   ```powershell
   uvicorn main:app --reload
   ```

Die Schritte 4–6 (Migrationen, Seed-Daten) sind nur beim ersten Einrichten nötig – nicht bei jedem Start.
