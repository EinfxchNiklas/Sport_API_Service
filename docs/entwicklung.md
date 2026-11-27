# Lokales Setup & Entwicklung

Diese Anleitung beschreibt, wie du die Sport Dashboard API lokal zum Laufen bringst.

---

## Voraussetzungen

- Python 3.14 (oder kompatibel)
- **Google Chrome** (aktuelle Stable-Version) – nur nötig, wenn du den Fußball-Import (WhoScored) lokal ausführen willst. `seleniumbase` lädt beim ersten Lauf automatisch den passenden `chromedriver` (und legt einen Ordner `downloaded_files/` an, der in `.gitignore` steht). Liegt Chrome an einem ungewöhnlichen Ort, setze `WHOSCORED_BROWSER_PATH`.
- Ein separates Neon-DEV-Projekt und eine Internetverbindung; alternativ Docker Desktop für eine lokale Datenbank → siehe [docker-anleitung.md](docker-anleitung.md)
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
python -m pip install -r requirements.txt
```

---

## Schritt 3: Umgebungsvariablen konfigurieren

Falls noch keine `.env` existiert, kopiere die Beispieldatei und trage deine Werte ein:

```powershell
copy .env.example .env
```

Eine bestehende `.env` mit eigenen Werten nicht überschreiben. Öffne sie in einem Texteditor und trage deine Werte ein. Eine Übersicht der Variablen:

| Variable                           | Beschreibung                                                                                   |
| ---------------------------------- | ---------------------------------------------------------------------------------------------- |
| `APP_ENV`                        | Umgebung: `development` oder `production`                                                  |
| `DATABASE_URL`                   | PostgreSQL-Verbindungs-URL (z. B. `postgresql+psycopg://sport:sport@localhost:5432/sportdb`) |
| `ADMIN_API_KEY`                  | Geheimer Schlüssel für Admin-Endpunkte (beliebiger sicherer Wert)                            |
| `SESSION_SECRET`                 | Signier-Schlüssel für das Admin-UI-Session-Cookie (`/admin`), beliebiger sicherer Wert     |
| `LOG_LEVEL`                      | Log-Level: `DEBUG`, `INFO`, `WARNING`, `ERROR`                                         |
| `ENABLE_SCHEDULER`               | Scheduler aktivieren: `true` oder `false`                                                  |
| `OPENF1_BASE_URL`                | Basis-URL der OpenF1-API (Standard: `https://api.openf1.org/v1`)                             |
| `TANK01_KEY`                     | RapidAPI-Schlüssel für Tank01 (NFL)                                                          |
| `TANK01_HOST`                    | RapidAPI-Host für Tank01                                                                      |
| `WHOSCORED_ENABLED`              | Fußball-Import (WhoScored) und -Jobs an/aus (Standard: `true`)                              |
| `WHOSCORED_LEAGUES`              | Aktive Wettbewerbe, kommagetrennt (Standard: `GER-Bundesliga`)                               |
| `WHOSCORED_HEADLESS`             | Chrome ohne Fenster starten (Standard: `true`; `false` zum Debuggen)                       |
| `WHOSCORED_BROWSER_PATH`         | Optional: Pfad zur Chrome-Binärdatei                                                          |
| `WHOSCORED_DATA_DIR`             | Optional: Cache-Verzeichnis von `soccerdata` (setzt `SOCCERDATA_DIR`)                      |
| `WHOSCORED_LOCK_TIMEOUT_SECONDS` | Maximale Wartezeit auf die Scraper-Sperre (Standard: `1800`)                                 |
| `TIMEZONE`                       | Zeitzone, z. B. `Europe/Berlin`                                                              |

> **Hinweis zu Datenquellen:** Details zu den Datenquellen und wo du die Keys bekommst, findest du in [datenquellen.md](datenquellen.md). WhoScored benötigt keinen Key, aber einen installierten Chrome.

> **Scheduler & Fußball:** Mit `ENABLE_SCHEDULER=true` und `WHOSCORED_ENABLED=true` startet beim Serverstart auch der Fußball-Bootstrap, der echte Scraping-Läufe gegen WhoScored startet. Für die lokale Entwicklung bleibt `ENABLE_SCHEDULER=false` meist die bessere Wahl. Zeitplan und Jobs: [scheduler.md](scheduler.md).

---

## Schritt 4: DEV-Datenbank einrichten

Erstelle bei [Neon](https://neon.com) ein separates DEV-Projekt, z. B. `sport-dashboard-dev`. Wähle im Projekt unter **Connect** Branch, Datenbank und Rolle und deaktiviere **Connection pooling** für die direkte Verbindung. Kopiere die URL ab `postgresql://` einschließlich aller Verbindungsparameter, ohne `psql` und ohne äußere Anführungszeichen, als Wert von `DATABASE_URL` in die lokale `.env`.

Der Connection-String enthält Zugangsdaten: nicht ins Repository oder in Nachrichten kopieren. Verwende für DEV niemals den Connection-String des separaten PROD-Projekts. Neon benötigt eine Internetverbindung; bei Inaktivität schläft die Recheninstanz ein und startet beim nächsten Zugriff automatisch.

Alternativ kann PostgreSQL lokal über Docker gestartet werden. Dazu muss `DATABASE_URL` in `.env` auf die lokale Docker-Datenbank zeigen. Detaillierte Anleitung: [docker-anleitung.md](docker-anleitung.md).

---

## Schritt 5: Datenbankmigrationen ausführen

Prüfe vor jedem Migrationslauf, dass `DATABASE_URL` auf die gewünschte **DEV-Datenbank** zeigt. Die Migration ändert die Datenbank, auf die diese URL verweist:

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
- **Datenbankverbindung prüfen:** [http://localhost:8000/api/v1/f1/drivers](http://localhost:8000/api/v1/f1/drivers) aufrufen; eine leere Liste ist bei einer neuen Datenbank normal. `/api/v1/health` allein prüft keine Datenbankverbindung.

---

## Tests ausführen

```powershell
pytest -q
```

Alle Tests befinden sich im Verzeichnis `tests/`. Die Tests benötigen weder Chrome noch Netzwerkzugriff auf WhoScored; der Scraper wird in den Tests ersetzt.

---

## Fußballdaten lokal importieren (CLI)

Mit installiertem Chrome und gesetzter `DATABASE_URL` (DEV-Datenbank!) kannst du Fußballdaten per Kommandozeile laden:

```powershell
# Registry der Wettbewerbe anzeigen (mit --live zusätzlich alle Wettbewerbe von WhoScored)
python -m app.football_cli competitions [--live]

# Saison importieren (Spielplan + Details beendeter Spiele)
python -m app.football_cli import-season --league GER-Bundesliga --season 2627 [--no-details] [--max-matches N]

# Ein einzelnes Spiel synchronisieren
python -m app.football_cli sync-match --ws-match-id 1234567 [--final]
```

Zum Ausprobieren bietet sich `--no-details` oder `--max-matches 3` an, denn der Scraper wartet ca. 7–10 Sekunden pro Seite. Mehr dazu in [datenquellen.md](datenquellen.md).

---

## Neue Datenbankmigration erstellen

Wenn du ein Datenbankmodell geändert hast, prüfe zuerst, dass `DATABASE_URL` auf DEV zeigt, und erstelle eine neue Migration:

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
2. **Nur bei Verwendung von Docker:** Container stoppen (Daten bleiben erhalten):
   ```powershell
   docker compose stop
   ```

Der Scheduler läuft im selben Prozess wie FastAPI und stoppt automatisch mit dem Server.

Bei Neon musst du die Datenbank nicht manuell stoppen. `docker compose stop` hält dagegen die lokalen Container an; ihre Daten im Volume `postgres_data` bleiben erhalten.

---

### Nächster Tag – Wieder loslegen

1. **Nur bei Verwendung von Docker:** Docker Desktop und anschließend die Container starten:
   ```powershell
   docker compose up -d
   ```
2. **Virtuelle Umgebung aktivieren** (falls noch nicht aktiv):
   ```powershell
   .venv\Scripts\activate
   ```
3. **FastAPI-Server starten:**
   ```powershell
   uvicorn main:app --reload
   ```

Migrationen sind beim ersten Einrichten und erneut nach neuen Migrationen nötig. Seed-Daten sind optional und müssen nicht bei jedem Start eingespielt werden.
