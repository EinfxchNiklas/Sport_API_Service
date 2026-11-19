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

- **`/admin`** – Dashboard mit Kennzahlen und Schnellaktionen (Datenimporte auslösen; Fußball-Importe laufen als Hintergrund-Jobs, Status in der Jobliste)
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

### Fußball (WhoScored)

Die Fußballdaten stammen von WhoScored und liegen normalisiert in der Datenbank. Die öffentlichen
Endpunkte lesen **nur** aus der DB (kein Auto-Import bei GET). Befüllt wird die DB über die
Admin-Importe (siehe unten) bzw. den Scheduler.

- `{slug}` ist der URL-Slug des Wettbewerbs (z. B. `bundesliga`, `2-bundesliga`, `dfb-pokal`, `premier-league`).
- `season` ist der Saison-Code (z. B. `2627` für 2026/27). Ohne Angabe wird die **neueste** Saison verwendet.
- Unbekannte Wettbewerbe, Saisons, Spiele oder Teams liefern `404`.
- Alle Zeitstempel sind Berliner Zeit (ISO 8601). WhoScored liefert keinen Spieltag.

| Methode | Pfad                                         | Auth | Beschreibung                                   | Query-Parameter |
|---------|----------------------------------------------|------|------------------------------------------------|-----------------|
| GET     | `/api/v1/football/competitions`              | Nein | Alle Wettbewerbe inkl. Saison-Codes            | —               |
| GET     | `/api/v1/football/{slug}/seasons`            | Nein | Saisons eines Wettbewerbs (neueste zuerst)     | —               |
| GET     | `/api/v1/football/{slug}/matches`            | Nein | Spiele, nach Anstoßzeit sortiert               | `season`, `team_id`, `status`, `date_from`, `date_to` |
| GET     | `/api/v1/football/{slug}/standings`          | Nein | Tabelle (aus abgeschlossenen Spielen berechnet) | `season`        |
| GET     | `/api/v1/football/{slug}/teams`              | Nein | Teams einer Saison                             | `season`        |
| GET     | `/api/v1/football/{slug}/missing-players`    | Nein | Ausfälle aller Teams der Saison                | `season`        |
| GET     | `/api/v1/football/matches/{match_id}`        | Nein | Spieldetails inkl. Ereignisse und Formationen  | —               |
| GET     | `/api/v1/football/matches/{match_id}/lineups`| Nein | Startelf und Bank beider Teams                 | —               |
| GET     | `/api/v1/football/matches/{match_id}/stats`  | Nein | Team- und Spielerstatistiken                   | —               |
| GET     | `/api/v1/football/teams/{team_id}`           | Nein | Team inkl. Land                                | —               |
| GET     | `/api/v1/football/teams/{team_id}/matches`   | Nein | Spiele eines Teams (auch wettbewerbsübergreifend) | `season_slug`, `season` |
| GET     | `/api/v1/football/teams/{team_id}/missing-players` | Nein | Ausfälle eines Teams                     | —               |

`status` ist einer von `scheduled`, `live`, `finished`, `postponed`, `cancelled`, `abandoned`.
`date_from`/`date_to` (Format `YYYY-MM-DD`, beide inklusive) filtern nach Anstoßzeit in Berliner Zeit.
`{match_id}`/`{team_id}` sind die **internen** IDs (nicht die WhoScored-IDs).

#### Beispiel: `GET /api/v1/football/competitions`

```json
[
  {
    "id": 1,
    "name": "Bundesliga",
    "slug": "bundesliga",
    "format": "league",
    "region": "Germany",
    "seasons": ["2627", "2526"]
  }
]
```

#### Beispiel: `GET /api/v1/football/bundesliga/matches?season=2627&status=finished`

```json
[
  {
    "id": 12,
    "ws_match_id": 1821234,
    "competition": "bundesliga",
    "season": "2627",
    "kickoff_time": "2026-08-22T15:30:00+02:00",
    "status": "finished",
    "home_team": {"id": 3, "name": "Bayern München"},
    "away_team": {"id": 7, "name": "RB Leipzig"},
    "home_score": 2,
    "away_score": 1,
    "ht_home_score": 1,
    "ht_away_score": 0,
    "et_home_score": null,
    "et_away_score": null,
    "pen_home_score": null,
    "pen_away_score": null
  }
]
```

#### Beispiel: `GET /api/v1/football/bundesliga/standings`

Die Tabelle wird bei jeder Anfrage aus den abgeschlossenen Spielen der Standard-Phase der Saison
berechnet (Siege 3, Unentschieden 1 Punkt). Sortierung: Punkte → Tordifferenz → erzielte Tore →
direkter Vergleich (Punkte, Tordifferenz, Auswärtstore) → Teamname. `form` enthält die letzten fünf
Ergebnisse (`W`/`D`/`L`), das neueste zuletzt. Für Pokalwettbewerbe (`format = "cup"`) gibt es keine
Tabelle (`404`).

```json
{
  "competition": "bundesliga",
  "season": "2627",
  "table": [
    {
      "position": 1,
      "team": {"id": 3, "name": "Bayern München"},
      "played": 3,
      "won": 3,
      "drawn": 0,
      "lost": 0,
      "goals_for": 9,
      "goals_against": 2,
      "goal_difference": 7,
      "points": 9,
      "form": ["W", "W", "W"]
    }
  ]
}
```

#### Beispiel: `GET /api/v1/football/matches/12`

`minute` ist die Anzeige-Minute inkl. Nachspielzeit (z. B. `"45+2"`). `team` ist das Team des Spielers
(bei Eigentoren das Team des Torschützen); `counts_for_team_id` nennt das Team, dem das Tor
gutgeschrieben wird (bei Eigentoren der Gegner). Ereignisse sind nach Spielzeit sortiert.

```json
{
  "id": 12,
  "ws_match_id": 1821234,
  "competition": "bundesliga",
  "season": "2627",
  "kickoff_time": "2026-08-22T15:30:00+02:00",
  "status": "finished",
  "home_team": {"id": 3, "name": "Bayern München"},
  "away_team": {"id": 7, "name": "RB Leipzig"},
  "home_score": 2,
  "away_score": 1,
  "venue": {"id": 1, "name": "Allianz Arena"},
  "referee": {"id": 4, "name": "Felix Zwayer"},
  "attendance": 75000,
  "started_at": "2026-08-22T15:30:41+02:00",
  "first_half_ended_at": "2026-08-22T16:17:50+02:00",
  "second_half_started_at": "2026-08-22T16:33:05+02:00",
  "home": {
    "team": {"id": 3, "name": "Bayern München"},
    "manager": "Vincent Kompany",
    "average_age": 26.4,
    "formations": [
      {
        "name": "4-2-3-1",
        "start_minute": 0,
        "end_minute": null,
        "period": 1,
        "captain": {"id": 10, "name": "Manuel Neuer"},
        "positions": [
          {"slot": 1, "player": {"id": 10, "name": "Manuel Neuer"}, "vertical": 0.0, "horizontal": 5.0}
        ]
      }
    ]
  },
  "away": {"team": {"id": 7, "name": "RB Leipzig"}, "manager": null, "average_age": null, "formations": []},
  "incidents": [
    {
      "id": 101,
      "type": "goal",
      "card_type": null,
      "minute": "45+2",
      "expanded_minute": 47,
      "period": "FirstHalf",
      "team": {"id": 3, "name": "Bayern München"},
      "counts_for_team_id": 3,
      "player": {"id": 21, "name": "Harry Kane"},
      "related_player": {"id": 22, "name": "Michael Olise"}
    }
  ],
  "sync_state": {
    "fixture_synced_at": "2026-08-22T18:00:00+02:00",
    "prematch_synced_at": null,
    "lineups_confirmed_at": null,
    "details_synced_at": "2026-08-22T18:05:00+02:00",
    "details_final_at": null,
    "last_attempt_at": "2026-08-22T18:05:00+02:00",
    "attempts": 1,
    "last_error": null
  }
}
```

#### Beispiel: `GET /api/v1/football/matches/12/lineups`

```json
{
  "match_id": 12,
  "home": {
    "team": {"id": 3, "name": "Bayern München"},
    "starters": [
      {
        "player": {"id": 10, "name": "Manuel Neuer"},
        "shirt_no": 1,
        "position": "GK",
        "rating": 7.1,
        "is_man_of_the_match": false,
        "age": 40,
        "subbed_in_minute": null,
        "subbed_out_minute": null
      }
    ],
    "bench": []
  },
  "away": {"team": {"id": 7, "name": "RB Leipzig"}, "starters": [], "bench": []}
}
```

#### Beispiel: `GET /api/v1/football/matches/12/stats`

```json
{
  "match_id": 12,
  "team_stats": {
    "home": {"shotsTotal": 14, "passesAccurate": 520},
    "away": {"shotsTotal": 9, "passesAccurate": 410}
  },
  "player_stats": [
    {
      "player": {"id": 10, "name": "Manuel Neuer"},
      "team_id": 3,
      "rating": 7.1,
      "stats": {"passesAccurate": 25, "shotsTotal": 0}
    }
  ]
}
```

#### Beispiel: `GET /api/v1/football/bundesliga/missing-players`

```json
[
  {
    "player": {"id": 33, "name": "Max Mustermann"},
    "team": {"id": 7, "name": "RB Leipzig"},
    "reason": "injured",
    "status": "Out",
    "updated_at": "2026-08-20T10:00:00+02:00",
    "match_id": 15
  }
]
```

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

| Methode | Pfad                                | Auth | Beschreibung                           | Query-Parameter                                              |
|---------|-------------------------------------|------|----------------------------------------|--------------------------------------------------------------|
| POST    | `/api/v1/admin/import/f1/races`     | Ja   | Importiert F1-Rennen für ein Jahr      | `year` (Pflicht)                                             |
| POST    | `/api/v1/admin/import/f1/drivers`   | Ja   | Importiert F1-Fahrer einer Session     | `session_key` (Pflicht)                                      |
| POST    | `/api/v1/admin/import/nfl/teams`    | Ja   | Importiert alle NFL-Teams              | —                                                            |
| POST    | `/api/v1/admin/import/nfl/games-new`| Ja   | Importiert NFL-Spiele                  | `week`, `season`, `season_type`                              |
| POST    | `/api/v1/admin/import/football/season` | Ja | Startet den WhoScored-Saisonimport (Hintergrund-Job) | `league` (Standard `GER-Bundesliga`), `season` (Standard: aktuelle Saison), `with_details` (Standard `true`), `max_matches` |
| POST    | `/api/v1/admin/import/football/match/{ws_match_id}` | Ja | Synchronisiert ein einzelnes Spiel (Hintergrund-Job) | `final` (Standard `false`) |
| GET     | `/api/v1/admin/jobs`                | Ja   | Hintergrund-Jobs (neueste zuerst)      | `limit` (Standard 50)                                        |
| GET     | `/api/v1/admin/jobs/{job_id}`       | Ja   | Status eines Hintergrund-Jobs          | —                                                            |

#### Fußball-Importe als Hintergrund-Jobs

Das Scrapen von WhoScored dauert pro Saison mehrere Minuten (ca. 10 s pro Seite) und nutzt einen
einzelnen Browser. Die Import-Endpunkte antworten deshalb sofort mit `202 Accepted` und starten
den Import im Hintergrund:

```bash
curl -X POST "http://localhost:8000/api/v1/admin/import/football/season?league=GER-Bundesliga&season=2627" \
  -H "X-API-Key: dein-geheimer-schluessel"
# → {"job_id": "3f9c1a2b7d4e"}

curl "http://localhost:8000/api/v1/admin/jobs/3f9c1a2b7d4e" -H "X-API-Key: dein-geheimer-schluessel"
```

```json
{
  "id": "3f9c1a2b7d4e",
  "name": "football-season GER-Bundesliga 2627",
  "group": "football",
  "status": "running",
  "created_at": "2026-11-19T17:40:00+01:00",
  "started_at": "2026-11-19T17:40:00+01:00",
  "finished_at": null,
  "result": null,
  "error": null
}
```

- `status`: `queued`, `running`, `success` oder `error` (`result` bzw. `error` enthalten das Ergebnis).
- Es kann immer nur **ein** Fußball-Import gleichzeitig laufen; ein weiterer Start liefert `409 Conflict`.
- Eine unbekannte `league` liefert `422` mit der Liste der gültigen Schlüssel (z. B. `GER-Bundesliga`,
  `GER-2. Bundesliga`, `GER-DFB-Pokal`, `ENG-Premier League`, …).
- Der Job-Status liegt nur im Arbeitsspeicher und geht bei einem Neustart der Anwendung verloren.

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
