# Deployment auf Render

Diese Anleitung beschreibt das Deployment der Sport Dashboard API auf [Render](https://render.com) mithilfe der `render.yaml`-Blueprint-Datei.

---

## Was ist ein Render Blueprint?

Die Datei `render.yaml` im Projekt-Root ist ein **Infrastructure-as-Code**-Blueprint für Render. Sie definiert automatisch alle benötigten Dienste (Web-Service + PostgreSQL-Datenbank), sodass du keine manuelle Konfiguration in der Render-Oberfläche vornehmen musst.

---

## Schritt 1: Repo mit Render verbinden

1. Melde dich an oder registriere dich auf [https://render.com](https://render.com).
2. Klicke auf **„New +"** → **„Blueprint"**.
3. Verbinde dein GitHub- oder GitLab-Repository (Render fragt nach Berechtigungen).
4. Wähle das Repository `Sport_Dashboard_API` aus.
5. Render erkennt die `render.yaml` automatisch und zeigt eine Vorschau der zu erstellenden Dienste.
6. Klicke auf **„Apply"**. Render erstellt:
   - Einen **Web Service** (FastAPI-Anwendung)
   - Eine **PostgreSQL-Datenbank**

---

## Schritt 2: Umgebungsvariablen auf Render

Einige Variablen werden von Render automatisch gesetzt, andere musst du manuell ergänzen.

### Automatisch gesetzte Variablen

| Variable        | Quelle                                                  |
|-----------------|---------------------------------------------------------|
| `DATABASE_URL`  | Wird automatisch aus der Render-PostgreSQL-Instanz generiert und dem Web Service übergeben. |

### Automatisch generierte Variablen

| Variable        | Beschreibung                                                    |
|-----------------|-----------------------------------------------------------------|
| `ADMIN_API_KEY` | Render generiert einen zufälligen sicheren Wert (`generateValue: true`). Den generierten Wert findest du im Render-Dashboard unter „Environment" des Web Service. Notiere ihn – du benötigst ihn für Admin-API-Aufrufe und den Login unter `/admin`. |
| `SESSION_SECRET`| Ebenfalls automatisch generiert (`generateValue: true`). Signiert das Session-Cookie der Admin-Weboberfläche (`/admin`). Ein manueller Login ist nach jeder Rotation dieses Werts erneut nötig. |

### Manuell zu setzende Variablen (`sync: false`)

Diese Variablen enthalten externe API-Keys und müssen im Render-Dashboard manuell eingetragen werden:

| Variable                | Wo eintragen                                  |
|-------------------------|-----------------------------------------------|
| `API_FOOTBALL_KEY`      | Render Dashboard → Web Service → Environment → „Add Environment Variable" |
| `TANK01_KEY`            | ebenso                                        |
| `TANK01_HOST`           | ebenso                                        |

So trägst du eine Variable ein:
1. Öffne den Web Service im Render-Dashboard.
2. Klicke auf **„Environment"** im linken Menü.
3. Klicke auf **„Add Environment Variable"**.
4. Trage Key und Wert ein, klicke auf **„Save Changes"**.
5. Render startet den Service automatisch neu.

---

## Schritt 3: Automatische Datenbankmigration

Die `render.yaml` definiert einen `buildCommand`, der vor jedem Deploy ausgeführt wird:

```
alembic upgrade head
```

Das bedeutet: Bei jedem neuen Deployment werden Datenbankmigrationen automatisch angewendet. Neue Tabellen oder Spalten sind sofort nach dem Deploy verfügbar – kein manuelles Eingreifen nötig.

---

## Health Check

Render überwacht den Dienst über den Health-Check-Endpunkt:

```
GET /api/v1/health
```

Dieser Endpunkt gibt `{"status": "ok"}` zurück und benötigt keinen API-Key. Render prüft ihn regelmäßig und startet den Service neu, wenn er nicht antwortet.

Du kannst denselben Endpunkt auch für **UptimeRobot** oder andere Monitoring-Dienste verwenden, um Ausfälle zu erkennen.

---

## Sicherheitshinweise

- **Datenbank nicht öffentlich:** Die Render-PostgreSQL-Instanz ist standardmäßig nur intern erreichbar. Öffne keinen öffentlichen Datenbankzugriff, es sei denn, du weißt genau, was du tust.
- **Secrets nur als ENV-Variablen:** Trage API-Keys und Passwörter ausschließlich als Umgebungsvariablen in Render ein. Schreibe sie niemals direkt in den Code oder in Dateien, die ins Repository committed werden.
- **Niemals Secrets ins Repo:** Die `.env`-Datei ist in `.gitignore` ausgeschlossen. Stelle sicher, dass sie niemals committet wird. Prüfe mit `git status`, ob sie unbeabsichtigt getrackt wird.
- **`ADMIN_API_KEY` schützen:** Dieser Key erlaubt das Auslösen von Datenimporten sowie den Login
  in der Admin-Weboberfläche (`/admin`). Verwende einen langen, zufälligen Wert und teile ihn nur
  mit vertrauenswürdigen Personen.
- **`SESSION_SECRET` schützen:** Signiert das Admin-Session-Cookie. Bei Kompromittierung rotieren
  (z. B. in Render neu generieren lassen) – bestehende Sessions werden dadurch ungültig.
