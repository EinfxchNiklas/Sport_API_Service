# Datenquellen

Die Sport Dashboard API bezieht ihre Daten aus drei Quellen: den öffentlichen bzw. Key-basierten APIs von OpenF1 und Tank01 sowie per Scraping von WhoScored (Fußball). Dieser Artikel beschreibt jede Quelle, welche Umgebungsvariablen benötigt werden und wie du die Keys einträgst.

> **Hinweis:** Der Fußball-Import (WhoScored) ist die einzige Quelle, die per Web-Scraping arbeitet. Beachte dazu den [rechtlichen Hinweis](#rechtlicher-hinweis) unten.

---

## OpenF1 (Formel 1)

**Website:** [https://openf1.org](https://openf1.org)

OpenF1 ist eine kostenlose, öffentliche API für Formel-1-Daten (Fahrer, Rennen, Sessions, Telemetrie).

- **API-Schlüssel:** Nicht erforderlich
- **Zugehörige Modelle:** `Race`, `Driver`
- **Zugehörige Endpunkte:** `/api/v1/f1/races`, `/api/v1/f1/drivers`

### Umgebungsvariablen

| Variable            | Pflicht | Beschreibung                                          |
|---------------------|---------|-------------------------------------------------------|
| `OPENF1_BASE_URL`   | Nein    | Basis-URL der API. Standard: `https://api.openf1.org/v1` |

Da kein API-Schlüssel nötig ist, kann `OPENF1_BASE_URL` entweder weggelassen (Standard wird verwendet) oder auf eine eigene Instanz gesetzt werden.

---

## WhoScored (Fußball)

**Website:** [https://www.whoscored.com](https://www.whoscored.com)

WhoScored liefert detaillierte Fußballdaten zu Ligen und Pokalwettbewerben. Es gibt keine offizielle API; die Daten werden mit der Bibliothek [`soccerdata`](https://github.com/probberechts/soccerdata) aus den Seiten von WhoScored gelesen („Scraping"). Dafür steuert `soccerdata` über `seleniumbase` einen echten Chrome-Browser.

- **API-Schlüssel:** Nicht erforderlich
- **Voraussetzung:** Ein installierter Google Chrome (lokal) bzw. das mitgelieferte Docker-Image (Render, siehe [deployment.md](deployment.md))
- **Zugehörige Endpunkte:** `/api/v1/football/...` (siehe [api.md](api.md))
- **Import:** per Scheduler (siehe [scheduler.md](scheduler.md)), Admin-Weboberfläche, Admin-API oder Kommandozeile (`python -m app.football_cli`)

### Welche Daten werden importiert?

- Spielplan, Spielstatus und Ergebnisse (inkl. Halbzeit, Verlängerung und Elfmeterschießen)
- Anstoß- und Halbzeit-Zeitstempel
- Karten und Tore
- Aufstellungen (Startelf und Bank) und Formationen
- Spieler-Ratings
- Spieler- und Teamstatistiken pro Spiel
- Schiedsrichter, Stadion, Zuschauerzahl und Trainer
- Verletzte und gesperrte Spieler (nur der aktuelle Stand, keine Historie)

**Nicht enthalten:** x/y-Koordinaten und der vollständige Event-Stream (Pässe, Schüsse mit Position usw.).

### Rate-Limit und Dauer

Der Scraper wartet bewusst etwa 7–10 Sekunden pro abgerufener Seite, um WhoScored nicht zu überlasten. Ein Saisonimport mit Details (rund 300 Spiele pro Bundesliga-Saison) dauert deshalb mehrere Dutzend Minuten und läuft als Hintergrund-Job. Zeitgleich läuft immer nur ein Scraper-Lauf (Postgres-Advisory-Lock und Browser-Lock im Prozess).

### Rechtlicher Hinweis

Die Nutzungsbedingungen von WhoScored verbieten das automatisierte Auslesen der Seiten (Scraping). Die Nutzung ist daher nur für **private, nicht-kommerzielle Zwecke und auf eigenes Risiko** gedacht. Gib die gescrapten Daten nicht weiter und veröffentliche keine öffentliche API darauf. Zudem kann WhoScored das Scraping technisch blockieren (Bot-Schutz) oder die Seitenstruktur jederzeit ändern; dann schlagen Importe fehl, bis `soccerdata` angepasst wurde.

### Unterstützte Wettbewerbe (Registry)

Die Wettbewerbe sind in `app/services/football_competitions.py` hinterlegt. Der **Schlüssel** (`league_key`) wird in `WHOSCORED_LEAGUES`, in der CLI (`--league`) und im Admin-Import verwendet.

| Schlüssel (`league_key`)  | Wettbewerb         | Slug (API)          | WhoScored-Region | WhoScored-Turnier |
|---------------------------|--------------------|---------------------|------------------|-------------------|
| `GER-Bundesliga`          | Bundesliga         | `bundesliga`        | 81 (Deutschland) | 3                 |
| `GER-2. Bundesliga`       | 2. Bundesliga      | `2-bundesliga`      | 81               | 6                 |
| `GER-DFB-Pokal`           | DFB-Pokal          | `dfb-pokal`         | 81               | 24                |
| `INT-Champions League`    | Champions League   | `champions-league`  | 250 (Europa)     | 12                |
| `INT-Europa League`       | Europa League      | `europa-league`     | 250              | 30                |
| `INT-Conference League`   | Conference League  | `conference-league` | 250              | 715               |
| `ENG-Premier League`      | Premier League     | `premier-league`    | 252 (England)    | 2                 |
| `ESP-La Liga`             | LaLiga             | `la-liga`           | 206 (Spanien)    | 4                 |
| `ITA-Serie A`             | Serie A            | `serie-a`           | 108 (Italien)    | 5                 |
| `FRA-Ligue 1`             | Ligue 1            | `ligue-1`           | 74 (Frankreich)  | 22                |

Standardmäßig ist nur `GER-Bundesliga` aktiv. Weitere Wettbewerbe aktivierst du kommagetrennt in `WHOSCORED_LEAGUES`, z. B. `WHOSCORED_LEAGUES=GER-Bundesliga,GER-2. Bundesliga`. Jeder zusätzliche Wettbewerb erhöht die Scraping-Last und die Laufzeit.

### Weiteren Wettbewerb hinzufügen

1. Die WhoScored-IDs (Region und Turnier) live abfragen:
   ```powershell
   python -m app.football_cli competitions --live
   ```
   Der Befehl zeigt die Registry aus dem Code; mit `--live` öffnet er zusätzlich Chrome und listet alle bei WhoScored verfügbaren Wettbewerbe mit ihren IDs.
2. In `app/services/football_competitions.py` einen weiteren `CompetitionConfig(...)`-Eintrag ergänzen (Schlüssel, Region-ID, Turnier-ID, Name, Slug, Format `league`/`cup`/`tournament`, Regionsname).
3. Den neuen Schlüssel in `WHOSCORED_LEAGUES` aufnehmen und die Saison importieren (siehe unten).

### Kommandozeile

```powershell
python -m app.football_cli competitions [--live]
python -m app.football_cli import-season --league GER-Bundesliga --season 2627 [--no-details] [--max-matches N]
python -m app.football_cli sync-match --ws-match-id 1234567 [--final]
```

Saison-Codes bestehen aus den beiden letzten Ziffern der Start- und Endjahre, z. B. `2627` für 2026/27.

### Umgebungsvariablen

| Variable                         | Pflicht | Beschreibung                                                                 |
|----------------------------------|---------|------------------------------------------------------------------------------|
| `WHOSCORED_ENABLED`              | Nein    | Football-Import und -Jobs an/aus. Standard: `true`                           |
| `WHOSCORED_LEAGUES`              | Nein    | Aktive Wettbewerbe, kommagetrennt (Registry-Schlüssel). Standard: `GER-Bundesliga` |
| `WHOSCORED_HEADLESS`             | Nein    | Chrome ohne Fenster starten. Standard: `true` (auf Servern erforderlich)     |
| `WHOSCORED_BROWSER_PATH`         | Nein    | Pfad zur Chrome-Binärdatei, falls sie nicht automatisch gefunden wird        |
| `WHOSCORED_DATA_DIR`             | Nein    | Cache-Verzeichnis von `soccerdata` (setzt `SOCCERDATA_DIR`). Standard: `~/soccerdata` |
| `WHOSCORED_LOCK_TIMEOUT_SECONDS` | Nein    | Maximale Wartezeit auf die Scraper-Sperre. Standard: `1800`                  |

### Bekannte Einschränkungen

- **Kein Spieltag:** WhoScored liefert keine Spieltagsnummer; die API kann Spiele daher nicht nach Spieltag gruppieren (nutze `date_from`/`date_to`).
- **DFB-Pokal:** In der Saison 2025/26 gab es bei WhoScored keine Match-Centre-Daten, daher stehen dort nur Ergebnisse zur Verfügung (keine Aufstellungen, Statistiken, Ereignisse).
- **Ausfälle (verletzt/gesperrt):** Die Liste stammt aus der Vorschau des nächsten Spiels und ist erst etwa einen Tag vor dem Anstoß verfügbar. Sie zeigt nur den aktuellen Stand.
- **Erstlauf:** Beim ersten Start wird ein passender `chromedriver` heruntergeladen (im Docker-Image bereits beim Build). Seleniumbase legt außerdem einen Ordner `downloaded_files/` im Arbeitsverzeichnis an (in `.gitignore` eingetragen).

---

## Tank01 (NFL)

**RapidAPI-Seite:** [https://rapidapi.com/tank01/api/tank01-nfl-live-in-game-real-time-statistics-nfl](https://rapidapi.com/tank01/api/tank01-nfl-live-in-game-real-time-statistics-nfl)

Tank01 stellt NFL-Live- und Historikdaten bereit und wird über die RapidAPI-Plattform bezogen.

- **API-Schlüssel:** Erforderlich (RapidAPI-Konto nötig)
- **Zugehörige Modelle:** `NflTeam`
- **Zugehörige Endpunkte:** `/api/v1/nfl/teams`, `/api/v1/nfl/games`

### Key besorgen

1. Registriere dich auf [https://rapidapi.com/](https://rapidapi.com/).
2. Öffne die Tank01-NFL-API-Seite (Link oben).
3. Klicke auf „Subscribe to Test" und wähle einen Plan.
4. Deinen Key findest du unter „Security" → „X-RapidAPI-Key" in der API-Konsole.

### Umgebungsvariablen

| Variable      | Pflicht | Beschreibung                                    |
|---------------|---------|-------------------------------------------------|
| `TANK01_KEY`  | Ja      | Dein `X-RapidAPI-Key` von RapidAPI              |
| `TANK01_HOST` | Ja      | Der RapidAPI-Host, z. B. `tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com` |

---

## Keys in `.env` eintragen

Öffne die Datei `.env` im Projekt-Root und trage die Werte ein:

```dotenv
# Formel 1 (kein Key nötig)
OPENF1_BASE_URL=https://api.openf1.org/v1

# Fußball (WhoScored, kein Key nötig – siehe oben)
WHOSCORED_ENABLED=true
WHOSCORED_LEAGUES=GER-Bundesliga
WHOSCORED_HEADLESS=true

# NFL
TANK01_KEY=dein_rapidapi_schluessel
TANK01_HOST=tank01-nfl-live-in-game-real-time-statistics-nfl.p.rapidapi.com
```

> **Sicherheitshinweis:** Füge die `.env`-Datei niemals in ein öffentliches Git-Repository ein. Sie ist in `.gitignore` ausgeschlossen.
