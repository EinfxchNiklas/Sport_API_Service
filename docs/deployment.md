# Deployment auf Render mit Neon

Diese Anleitung beschreibt das Deployment der Sport Dashboard API auf [Render](https://render.com) mit einer separaten PostgreSQL-Datenbank bei [Neon](https://neon.com).

---

## Was ist ein Render Blueprint?

Die Datei `render.yaml` im Projekt-Root ist ein **Infrastructure-as-Code**-Blueprint für Render. Sie definiert den Web Service, erstellt aber keine Datenbank. Die Neon-Verbindung wird als geheime Umgebungsvariable im Render-Dashboard hinterlegt.

Der Web Service läuft als **Docker-Dienst** (`runtime: docker`, Build aus dem `Dockerfile` im Projekt-Root). Das ist nötig, weil der WhoScored-Scraper einen echten Chrome-Browser braucht und Renders native Python-Laufzeit keinen Chrome enthält. Das Image basiert auf `python:3.14-slim`, installiert Google Chrome (amd64) und lädt `chromedriver` schon beim Build.

---

## Schritt 1: Neon vorbereiten

1. Erstelle bei Neon ein separates Produktionsprojekt, z. B. `sport-dashboard-prod`.
2. Klicke in diesem Projekt auf **Connect** und wähle Branch, Datenbank und Rolle aus.
3. Deaktiviere für diesen Blueprint **Connection pooling** und kopiere den direkten PostgreSQL-Connection-String. Dieselbe Verbindung wird für die Anwendung und die Alembic-Migrationen verwendet.
4. Kopiere nur die URL ab `postgresql://` einschließlich der Verbindungsparameter, ohne `psql` und ohne umgebende Anführungszeichen. Behandle sie als Passwort.

Verwende nicht die URL des DEV-Projekts. Eine neu erstellte Datenbank ist leer; vorhandene Daten werden nicht automatisch übernommen.

## Schritt 2: Repo mit Render verbinden

1. Melde dich an oder registriere dich auf [https://render.com](https://render.com).
2. Klicke auf **„New +"** → **„Blueprint"**.
3. Verbinde dein GitHub- oder GitLab-Repository (Render fragt nach Berechtigungen).
4. Wähle das Repository `Sport_Dashboard_API` aus.
5. Render erkennt die `render.yaml` automatisch und zeigt eine Vorschau der zu erstellenden Dienste.
6. Gib bei der Einrichtung für `DATABASE_URL` den direkten Connection-String des **PROD**-Projekts ein. Gib vorhandene API-Keys (z. B. `TANK01_KEY`) bei Bedarf ebenfalls ein.
7. Klicke auf **„Apply"**. Render baut das Docker-Image (der erste Build dauert wegen Chrome einige Minuten) und erstellt einen **Web Service** für die FastAPI-Anwendung, aber keine Render-PostgreSQL-Datenbank.

---

## Schritt 3: Umgebungsvariablen auf Render

Einige Variablen werden von Render automatisch gesetzt, andere musst du manuell ergänzen.

### Automatisch generierte Variablen

| Variable        | Beschreibung                                                    |
|-----------------|-----------------------------------------------------------------|
| `ADMIN_API_KEY` | Render generiert einen zufälligen sicheren Wert (`generateValue: true`). Den generierten Wert findest du im Render-Dashboard unter „Environment" des Web Service. Notiere ihn – du benötigst ihn für Admin-API-Aufrufe und den Login unter `/admin`. |
| `SESSION_SECRET`| Ebenfalls automatisch generiert (`generateValue: true`). Signiert das Session-Cookie der Admin-Weboberfläche (`/admin`). Ein manueller Login ist nach jeder Rotation dieses Werts erneut nötig. |

### Manuell zu setzende Variablen (`sync: false`)

Diese Werte werden bei der Blueprint-Erstellung abgefragt und können im Render-Dashboard verwaltet werden:

| Variable                | Wo eintragen                                  |
|-------------------------|-----------------------------------------------|
| `DATABASE_URL`          | Direkter Connection-String der Neon-Produktionsdatenbank |
| `TANK01_KEY`            | Render Dashboard → Web Service → Environment → „Add Environment Variable" |

`TANK01_HOST` hat einen Standardwert in der Anwendung und muss nur bei Bedarf zusätzlich gesetzt werden.

### Feste Variablen aus der `render.yaml`

| Variable             | Wert           | Beschreibung                                                          |
|----------------------|----------------|-----------------------------------------------------------------------|
| `ENABLE_SCHEDULER`   | `true`         | Startet den APScheduler im Web-Prozess (auch die Football-Jobs)        |
| `LOG_LEVEL`          | `INFO`         | Log-Level                                                             |
| `APP_ENV`            | `production`   | Laufzeitumgebung                                                      |
| `WHOSCORED_ENABLED`  | `true`         | WhoScored-Import und Football-Jobs an/aus (`false` = Scraper aus)     |
| `WHOSCORED_LEAGUES`  | `GER-Bundesliga` | Aktive Wettbewerbe, kommagetrennt (Schlüssel siehe [datenquellen.md](datenquellen.md)) |
| `WHOSCORED_HEADLESS` | `true`         | Chrome ohne Fenster (auf Servern zwingend)                            |

Optional (nicht in der `render.yaml`): `WHOSCORED_BROWSER_PATH`, `WHOSCORED_DATA_DIR` (im Image ist `SOCCERDATA_DIR=/tmp/soccerdata` gesetzt) und `WHOSCORED_LOCK_TIMEOUT_SECONDS`. Einen `API_FOOTBALL_KEY` gibt es nicht mehr; WhoScored benötigt keinen Schlüssel.

So trägst du eine Variable ein:
1. Öffne den Web Service im Render-Dashboard.
2. Klicke auf **„Environment"** im linken Menü.
3. Klicke auf **„Add Environment Variable"**.
4. Trage Key und Wert ein und speichere. Render startet den Dienst neu; beim Start laufen die Migrationen erneut (siehe Schritt 4).

Bei späteren Blueprint-Updates werden `sync: false`-Werte nicht automatisch überschrieben; ändere sie bei Bedarf im Dashboard.

---

## Schritt 4: Datenbankmigration und Verbindung prüfen

Der Start-Befehl steht im `Dockerfile` (`CMD`) und führt bei **jedem Containerstart** zuerst die Migrationen und dann den Server aus:

```
alembic upgrade head && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Der Server läuft bewusst mit **genau einem Worker**, weil der Browser-Lock des Scrapers (und der Scheduler) pro Prozess gelten.

Warum nicht `preDeployCommand`? Laut [Render-Dokumentation](https://render.com/docs/deploys#pre-deploy-command) ist der Pre-Deploy-Befehl nur für bezahlte Dienste verfügbar; auf dem Free-Plan würde er nicht laufen. Deshalb werden die Migrationen im `CMD` ausgeführt. Bei jedem Start (auch nach dem Aufwachen/Neustart) werden sie auf die durch `DATABASE_URL` bezeichnete Datenbank angewendet; bereits angewendete Migrationen werden übersprungen. Prüfe die Deploy-Logs auf eine erfolgreiche Migration. Achte insbesondere darauf, dass `DATABASE_URL` auf PROD zeigt. Schlägt die Migration fehl, startet der Server nicht.

Teste nach dem Deployment neben dem Health Check auch einen datenbankgestützten Endpunkt, z. B. `GET /api/v1/f1/drivers`. Eine leere Liste ist bei einer neuen Datenbank normal.

---

## Health Check

Render überwacht den Dienst über den Health-Check-Endpunkt:

```
GET /api/v1/health
```

Dieser Endpunkt gibt `{"status": "ok"}` zurück und benötigt keinen API-Key. Er prüft **nicht** die Datenbankverbindung.

Du kannst denselben Endpunkt auch für **UptimeRobot** oder andere Monitoring-Dienste verwenden, um Ausfälle zu erkennen.

---

## Sicherheitshinweise

- **Neon-Verbindung schützen:** Verwende TLS und bewahre den Connection-String vertraulich auf. Neon empfiehlt für vollständige Zertifikats- und Hostnamenprüfung `sslmode=verify-full` mit korrekt eingerichteten Root-Zertifikaten; siehe [Neon-Dokumentation](https://neon.com/docs/connect/connect-securely).
- **Secrets nur als ENV-Variablen:** Trage API-Keys und Passwörter ausschließlich als Umgebungsvariablen in Render ein. Schreibe sie niemals direkt in den Code oder in Dateien, die ins Repository committed werden.
- **Niemals Secrets ins Repo:** Die `.env`-Datei ist in `.gitignore` ausgeschlossen. Stelle sicher, dass sie niemals committet wird. Prüfe mit `git status`, ob sie unbeabsichtigt getrackt wird.
- **`ADMIN_API_KEY` schützen:** Dieser Key erlaubt das Auslösen von Datenimporten sowie den Login
  in der Admin-Weboberfläche (`/admin`). Verwende einen langen, zufälligen Wert und teile ihn nur
  mit vertrauenswürdigen Personen.
- **`SESSION_SECRET` schützen:** Signiert das Admin-Session-Cookie. Bei Kompromittierung rotieren
  (z. B. in Render neu generieren lassen) – bestehende Sessions werden dadurch ungültig.
- **Backups:** Sichere Daten regelmäßig separat und teste die Wiederherstellung. Der kostenlose Neon-Tarif hat nur eine begrenzte Wiederherstellungshistorie.

## Dauerbetrieb mit UptimeRobot (kostenloser Render-Webdienst)

Der kostenlose Render-Webdienst schläft nach etwa 15 Minuten ohne eingehende Anfragen ein; der in der Anwendung laufende APScheduler würde dann keine Jobs mehr ausführen. Als Gegenmaßnahme pingt [UptimeRobot](https://uptimerobot.com) den Health-Check (`GET /api/v1/health`) alle 10 Minuten und hält den Dienst wach. Damit laufen die Scheduler-Jobs (u. a. die Football-Jobs, siehe [scheduler.md](scheduler.md)) zuverlässig im Web-Prozess; eine separate Scheduling-Lösung ist nicht nötig. Fällt der Ping aus oder wird der Dienst neu gestartet, holt der stündliche Catch-up-Job verpasste Spiele nach.

Der Health-Check berührt die Datenbank nicht; Neon kann daher weiterhin einschlafen, bis ein Job oder ein Datenendpunkt sie wieder anspricht.

---

## WhoScored auf Render

Der Fußball-Import startet einen echten Chrome-Browser im selben Container wie die API. Das funktioniert im Docker-Image, hat auf dem kostenlosen Render-Plan aber reale Risiken. Sie sind **nicht** vorab verifiziert – prüfe nach dem ersten Deploy die Logs.

### Risiken

- **Arbeitsspeicher (512 MB):** Der Free-Plan bietet 512 MB RAM (und nur 0,1 CPU). Ein headless Chrome braucht typischerweise rund 250–450 MB zusätzlich zur FastAPI-Anwendung. Es besteht ein echtes Risiko für Out-of-Memory-Abbrüche („Instance failed … ran out of memory"); der Dienst wird dann neu gestartet und ein laufender Scraper-Lauf geht verloren. Mit nur 0,1 CPU ist der Browser außerdem langsam; Timeouts sind möglich. Die Anwendung nutzt nur einen Worker und höchstens einen Browser gleichzeitig, um den Speicherbedarf zu begrenzen.
- **Blockierung von Rechenzentrums-IPs:** WhoScored schützt sich mit Bot-Erkennung (Cloudflare/Incapsula). IP-Adressen von Cloud-Anbietern werden dabei häufiger blockiert als Heimanschlüsse. Ob die Render-IPs funktionieren, ist offen. Typische Anzeichen: wiederholte Fehler oder Timeouts im Scraper-Log, Captcha-Seiten (im Headless-Modus nicht lösbar).
- **Erster Lauf:** `chromedriver` wird bereits beim Docker-Build passend zur installierten Chrome-Version geladen. Falls er zur Laufzeit trotzdem nachgeladen werden muss (z. B. nach einem Chrome-Update im Basis-Image), dauert der erste Lauf länger. Das Dateisystem des Free-Plans ist flüchtig: der Cache unter `/tmp/soccerdata` geht bei jedem Neustart verloren, bereits geladene Seiten werden dann erneut abgerufen.
- **Rate-Limit:** Der Scraper wartet ca. 7–10 s pro Seite. Ein kompletter Saisonimport dauert dadurch lange und ist auf dem Free-Plan besonders OOM-anfällig.

### Fallback: Scraper an anderer Stelle betreiben

Funktioniert der Scraper auf Render nicht stabil, kann er auf einem anderen Rechner laufen (lokaler PC mit Chrome oder ein kleiner VPS), der in **dieselbe Neon-Datenbank** schreibt:

1. Auf Render die Variable `WHOSCORED_ENABLED=false` setzen. Die API liefert weiter die Daten aus Neon aus, startet aber keinen Browser und keine Football-Jobs.
2. Auf dem anderen Rechner die Anwendung mit derselben `DATABASE_URL` betreiben und `ENABLE_SCHEDULER=true`, `WHOSCORED_ENABLED=true` setzen (lokal: `uvicorn main:app`; auf einem VPS z. B. das Docker-Image aus diesem Repository). Der Scheduler dort übernimmt die Football-Jobs (siehe [scheduler.md](scheduler.md)).
3. Die Verbindung zu Neon geht über das Internet; die DB-Zugangsdaten gehören nur auf Rechner, denen du vertraust.

Ein **Postgres-Advisory-Lock** verhindert, dass zwei Instanzen gleichzeitig scrapen; falls versehentlich beide aktiv sind, wartet bzw. überspringt die zweite Instanz den Lauf. Trotzdem sollte nur eine Stelle dauerhaft scrapen.

### Erstbefüllung der Daten

- Der **Bootstrap-Job** beim Start befüllt die aktuelle Saison der aktiven Wettbewerbe automatisch (Spielplan, Details beendeter Spiele). Dies kann lange dauern (siehe Rate-Limit).
- Die **Vorsaison** (und ältere) importierst du bei Bedarf manuell:
  - über die Admin-Weboberfläche (`/admin`, Karten für Hintergrund-Importe) oder `POST /api/v1/admin/import/football/season?league=GER-Bundesliga&season=2526` (siehe [api.md](api.md)), oder
  - per CLI auf einem Rechner mit Chrome und Zugriff auf die Zieldatenbank:
    ```powershell
    python -m app.football_cli import-season --league GER-Bundesliga --season 2526
    ```
- Zeitplan, Jobs und Sperren im Detail: [scheduler.md](scheduler.md).
