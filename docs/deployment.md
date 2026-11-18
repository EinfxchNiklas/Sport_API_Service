# Deployment auf Render mit Neon

Diese Anleitung beschreibt das Deployment der Sport Dashboard API auf [Render](https://render.com) mit einer separaten PostgreSQL-Datenbank bei [Neon](https://neon.com).

---

## Was ist ein Render Blueprint?

Die Datei `render.yaml` im Projekt-Root ist ein **Infrastructure-as-Code**-Blueprint für Render. Sie definiert den Web Service, erstellt aber keine Datenbank. Die Neon-Verbindung wird als geheime Umgebungsvariable im Render-Dashboard hinterlegt.

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
6. Gib bei der Einrichtung für `DATABASE_URL` den direkten Connection-String des **PROD**-Projekts ein. Gib vorhandene API-Keys bei Bedarf ebenfalls ein.
7. Klicke auf **„Apply"**. Render erstellt einen **Web Service** für die FastAPI-Anwendung, aber keine Render-PostgreSQL-Datenbank.

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
| `API_FOOTBALL_KEY`      | Render Dashboard → Web Service → Environment → „Add Environment Variable" |
| `TANK01_KEY`            | ebenso                                        |

`TANK01_HOST` hat einen Standardwert in der Anwendung und muss nur bei Bedarf zusätzlich gesetzt werden.

So trägst du eine Variable ein:
1. Öffne den Web Service im Render-Dashboard.
2. Klicke auf **„Environment"** im linken Menü.
3. Klicke auf **„Add Environment Variable"**.
4. Trage Key und Wert ein und wähle **Save, rebuild, and deploy**, wenn die Datenbankverbindung geändert wurde: Nur ein neuer Build führt den konfigurierten Migrationsbefehl aus.

Bei späteren Blueprint-Updates werden `sync: false`-Werte nicht automatisch überschrieben; ändere sie bei Bedarf im Dashboard.

---

## Schritt 4: Datenbankmigration und Verbindung prüfen

Die `render.yaml` definiert einen `buildCommand`, der beim Build ausgeführt wird:

```
alembic upgrade head
```

Bei einem neuen Build werden die Migrationen auf die durch `DATABASE_URL` bezeichnete Datenbank angewendet. Ein Redeploy ohne neuen Build führt sie nicht erneut aus. Prüfe die Build-Logs auf eine erfolgreiche Migration. Achte insbesondere darauf, dass `DATABASE_URL` auf PROD zeigt.

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

## Einschränkung des kostenlosen Render-Webdienstes

Der Free-Webdienst schläft bei Inaktivität ein. Der in der Anwendung laufende APScheduler kann daher während dieser Zeit keine Jobs zuverlässig nach Zeitplan ausführen. Für regelmäßige Importe ist eine separate Scheduling-Lösung erforderlich. Der WhoScored-Import ist derzeit nicht in die API integriert.
