# API-Referenz

Alle Endpunkte haben den Präfix `/api/v1`.

Die vollständige, interaktive API-Dokumentation ist nach dem Start der Anwendung erreichbar unter:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## Authentifizierung

Admin-Endpunkte erfordern einen API-Schlüssel im HTTP-Header:

```
X-API-Key: <dein ADMIN_API_KEY>
```

Der Wert muss mit der Umgebungsvariable `ADMIN_API_KEY` übereinstimmen. Öffentliche GET-Endpunkte benötigen keinen Key.

---

## Admin-Weboberfläche (`/admin`)

Zusätzlich zur REST-API gibt es eine browserbasierte, gesicherte Admin-Oberfläche:

- **`/admin`** – Dashboard mit Kennzahlen und Schnellaktionen (Datenimporte auslösen)
- **`/admin/schedulers`** – Scheduler-Jobs ansehen, pausieren/fortsetzen, sofort ausführen, Ausführungshistorie
- **`/admin/architecture`** – interaktiver Graph: Endpunkt → Service → Datenquelle/DB-Tabelle → Scheduler-Job
- **`/admin/endpoints`** – tabellarische Endpunkt-Referenz mit Datenfluss

**Login:** unter `/admin/login` mit dem `ADMIN_API_KEY` anmelden; danach wird ein signiertes,
HTTP-only Session-Cookie gesetzt (Signierschlüssel: `SESSION_SECRET`). Die REST-Endpunkte unter
`/admin/api/...` akzeptieren sowohl dieses Cookie als auch weiterhin den `X-API-Key`-Header.

---

## Endpunkte

### Health

| Methode | Pfad             | Auth | Beschreibung              | Query-Parameter |
|---------|------------------|------|---------------------------|-----------------|
| GET     | `/api/v1/health` | Nein | Gibt `{"status":"ok"}` zurück | —           |

---

### Bundesliga

| Methode | Pfad                        | Auth | Beschreibung                        | Query-Parameter |
|---------|-----------------------------|------|-------------------------------------|-----------------|
| GET     | `/api/v1/bundesliga/table`  | Nein | Aktuelle Tabelle der Bundesliga      | —               |
| GET     | `/api/v1/bundesliga/matches`| Nein | Gespielte und anstehende Spiele      | —               |

---

### Formel 1

| Methode | Pfad                | Auth | Beschreibung             | Query-Parameter |
|---------|---------------------|------|--------------------------|-----------------|
| GET     | `/api/v1/f1/races`  | Nein | Liste aller F1-Rennen    | —               |
| GET     | `/api/v1/f1/drivers`| Nein | Liste aller F1-Fahrer    | —               |

---

### NFL

| Methode | Pfad                 | Auth | Beschreibung           | Query-Parameter |
|---------|----------------------|------|------------------------|-----------------|
| GET     | `/api/v1/nfl/teams`  | Nein | Liste aller NFL-Teams  | —               |
| GET     | `/api/v1/nfl/games`  | Nein | Liste aller NFL-Spiele | —               |

---

### Admin – Datenimport

Alle Admin-Endpunkte erfordern den Header `X-API-Key`.

| Methode | Pfad                              | Auth | Beschreibung                           | Query-Parameter                                              |
|---------|-----------------------------------|------|----------------------------------------|--------------------------------------------------------------|
| POST    | `/api/v1/admin/import/bundesliga` | Ja   | Importiert Bundesliga-Daten            | `season` (Pflicht), `league_id` (Pflicht)                    |
| POST    | `/api/v1/admin/import/f1/races`   | Ja   | Importiert F1-Rennen für ein Jahr      | `year` (Pflicht)                                             |
| POST    | `/api/v1/admin/import/f1/drivers` | Ja   | Importiert F1-Fahrer einer Session     | `session_key` (Pflicht)                                      |
| POST    | `/api/v1/admin/import/nfl/teams`  | Ja   | Importiert alle NFL-Teams              | —                                                            |
| POST    | `/api/v1/admin/import/nfl/games`  | Ja   | Importiert NFL-Spiele                  | `game_week` (Pflicht), `season` (Pflicht), `season_type` (Pflicht) |

---

## Beispiel-Aufruf (curl)

Öffentlicher Endpunkt:

```bash
curl http://localhost:8000/api/v1/health
```

Admin-Endpunkt mit API-Key:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/import/nfl/teams" \
  -H "X-API-Key: dein-geheimer-schluessel"
```
