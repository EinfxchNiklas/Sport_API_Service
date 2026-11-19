# Scheduler

Alle Hintergrundjobs laufen im `BackgroundScheduler` (APScheduler 3, Zeitzone `Europe/Berlin`) in
`app/schedulers/scheduler.py`. Der Scheduler startet nur, wenn `ENABLE_SCHEDULER=true` gesetzt ist.
Die Fußball-Jobs liegen in `app/schedulers/football_jobs.py` und werden nur registriert, wenn zusätzlich
`WHOSCORED_ENABLED=true` ist.

## Übersicht der Jobs

| Job-ID | Trigger | Zweck |
|---|---|---|
| `nightly_session_status_update` | Cron täglich 03:00 | F1: Session-Status `upcoming` → `completed` (keine externen Aufrufe) |
| `hourly_f1_data_fetch` | Intervall 1 h | F1: fehlende Session-Ergebnisse (OpenF1) und Standings nachladen |
| `football_daily_sync` | Cron täglich 04:00 | Spielpläne aktualisieren, finaler Detail-Nachlauf |
| `football_matchday_tick` | Intervall 3 min | Prematch, Aufstellungs-Retry, Post-Match-Polling (aus Cache entschieden) |
| `football_hourly_catchup` | Cron stündlich, Minute 17 | fehlende Match-Details nachladen, überfällige Spielstatus korrigieren |
| `football_bootstrap` | einmalig ~60 s nach Start | Erst-Import, wenn die aktuelle Saison eines Wettbewerbs noch leer ist |

Alle Fußball-Jobs: `max_instances=1`, `coalesce=True`, jeweils passende `misfire_grace_time`. Der frühere
Per-Match-Monitor (`schedule_match_monitor`) wurde entfernt. Die Jobs sind in der Admin-UI sichtbar und
können dort pausiert/gestartet werden.

### Fußball-Jobs im Detail

**`football_daily_sync` (04:00)** – für jeden Wettbewerb aus `WHOSCORED_LEAGUES`:

- Saison = `current_season_code()` (Saisonwechsel im Juli), `ensure_season` lädt keine Seite, wenn sie existiert.
- Saison hat noch keine Spiele → kompletter Kalender (Bootstrap).
- Montags → kompletter Kalender (fängt weit in der Zukunft verschobene Spiele ab).
- Sonst inkrementell: aktueller und nächster Monat; zusätzlich der Vormonat, solange heute der 7. oder früher ist
  (Nachzügler, Nachholspiele).
- Danach „Nachladen“: beendete Spiele der letzten 14 Tage mit Details (`details_synced_at`), aber ohne finalen Lauf
  (`details_final_at`), Anpfiff ≥ 6 h her → `sync_match_details(final=True)` (nur Upsert/Ergänzung).

**`football_matchday_tick` (alle 3 min)** – entscheidet ausschließlich aus dem In-Memory-Cache (siehe unten):

1. *Prematch* (45 min vor Anpfiff): Spiele mit Status `scheduled`, Anpfiff in `(jetzt, jetzt+45 min]`, Prematch noch
   nicht erfolgt. Die fälligen Spiele werden nach (Stage, Berliner Jahr/Monat) gruppiert; pro Gruppe wird der
   Fixture-Monat **einmal** per `sync_stage_month` geladen (liefert zugleich `has_preview` je Spiel). Danach folgt
   pro Spiel `sync_prematch(refresh_fixtures=False, has_preview=…)`: Vorschau/Ausfälle (nur falls Preview vorhanden)
   und Match Centre mit Aufstellungen. Schlägt der Gruppen-Refresh fehl, wird die Gruppe im nächsten Tick erneut
   versucht. „Erfolgt“ heißt: `prematch_synced_at` **oder** `fixture_synced_at` liegt nach T-45 min (die
   Vorschau-Marke wird nur bei vorhandener Preview gesetzt, der Fixture-Refresh läuft immer). Direkte Aufrufe von
   `sync_prematch` (ohne Parameter) laden weiterhin selbst den Fixture-Monat.
2. *Zweiter Aufstellungsversuch*: `lineups_confirmed_at` noch leer, Anpfiff in `(jetzt, jetzt+20 min]`, letzter
   Detail-Versuch (`details_synced_at`/`last_attempt_at`) älter als T-30 min → nur `sync_match_details`. Da der
   Versuch selbst einen Zeitstempel setzt, passiert das genau einmal (keine zusätzlichen Spalten nötig).
3. *Post-Match*: Status `scheduled`/`live`, Anpfiff + 105 min ≤ jetzt ≤ Anpfiff + 6 h → Spiele werden nach
   (Stage, Berliner Jahr/Monat) gruppiert, pro Gruppe wird **eine** Fixture-Seite geladen (deckt alle parallelen
   Spiele ab); für jedes dadurch auf `finished` gewechselte Spiel folgt sofort `sync_match_details` in derselben
   Browser-Session. Drosselung: Polling je Gruppe höchstens alle 2 min (bis Anpfiff+150 min), danach alle 10 min.
   Bereits beendete Spiele, deren Details noch fehlen, werden im Tick bis zu 4 Mal (Abstand ≥ 5 min) versucht.

Ist nichts fällig, kehrt der Tick sofort zurück: keine DB-Abfrage, kein Client, kein Browser.

**`football_hourly_catchup` (:17)** – entscheidet ebenfalls zuerst aus dem Cache:

- Beendete Spiele der letzten 14 Tage ohne Details, `attempts < 8`, letzter Versuch ≥ 30 min her →
  `sync_match_details` (maximal 25 pro Lauf, älteste zuerst).
- Spiele, die laut DB noch `scheduled`/`live` sind, obwohl Anpfiff + 6 h vorbei ist → deren Stage-Monat wird einmal
  aktualisiert (Statuskorrektur, z. B. `postponed`/`abandoned`); wechselt ein Spiel dabei auf `finished`, werden die
  Details gleich mitgeladen.
- Spiele ohne Match Centre (z. B. DFB-Pokal-Spiele kleinerer Vereine) werden nach 8 Versuchen nicht mehr abgerufen
  (Tick: Versuche 1–4, Catch-up: 5–8).

**`football_bootstrap` (+60 s nach Start)** – lädt immer den Spielplan-Cache und prüft per DB, welche aktuellen Saisons
noch keine Spiele haben. Nur dafür wird (mit einem Client) der komplette Kalender importiert. Eine frische Installation
füllt sich damit selbst; Details der letzten 14 Tage holt anschließend der Catch-up nach (25/h). Vorsaisons bleiben
manuell (Admin-Import/CLI).

## Ablauf eines typischen Bundesliga-Samstags (Anpfiff 15:30)

| Zeit | Was passiert |
|---|---|
| 04:00 | Daily-Sync: Fixtures aktueller + nächster Monat, finale Reloads der Vortagsspiele |
| 14:45 | Tick: Prematch – 1 Fixture-Seite für den Monat, dann je Spiel Preview + Match Centre (ggf. mit Aufstellungen) |
| 15:09–15:12 | Tick: zweiter Aufstellungsversuch (T-20 min), falls Aufstellungen noch fehlen |
| 15:30 | Anpfiff – während des Spiels kein Scraping |
| ~17:15 | erstes Post-Match-Polling (Anpfiff + 105 min): 1 Fixture-Seite für den Monat, wechselt ein Spiel auf `finished` → sofort Match Centre |
| ~17:17–17:30 | weitere Polls im 3-min-Takt (ab Fenster 2 min Mindestabstand), restliche Spiele werden fertig; Daten in der DB ~5–15 min nach Abpfiff |
| 17:17 / 18:17 … | stündlicher Catch-up greift Nachzügler auf |
| nächster Morgen 04:00 | Daily-Sync lädt die Details der Spiele als finalen Lauf neu (≥ 6 h nach Anpfiff) |

### Scraping-Budget pro Spieltag (9 Spiele, geschätzt)

Seitenladung ≈ 7–10 s, Browser-Start ≈ 6 s je Lauf (nur wenn etwas fällig ist).

| Phase | Seiten |
|---|---|
| Prematch: je (Stage, Monat)-Gruppe 1 Fixture-Seite (parallele Spiele teilen sie) + je Spiel Preview (1, falls vorhanden) + Match Centre (1) | 5 parallele Spiele im selben Monat: 1 + 5 × 2 = 11; 9 Spiele über mehrere Anpfiffzeiten: ~3–4 Fixture-Seiten + 9 × 2 = **~21–22** |
| Post-Match-Polling: je (Stage, Monat)-Gruppe 2–4 Fixture-Seiten pro Anpfiffzeit | ~ **6–12** |
| Match Centre nach Abpfiff | 9 |
| Daily-Sync am nächsten Morgen: 2 Fixture-Monate + 9 finale Match Centres | ~ **11** |
| Catch-up | meist 0–1 |

Summe ≈ 48–52 Seiten ≈ 7–9 Minuten reine Ladezeit, verteilt über den Tag auf rund 15–25 Tick-Läufe mit je einem Browser.

### Wie oft wird Catch-up gebraucht?

WhoScored veröffentlicht das Match Centre meist innerhalb weniger Minuten nach dem Abpfiff. Erwartung: **0–1 von 9
Spielen pro Spieltag** brauchen den Catch-up – hauptsächlich bei Verzögerungen auf WhoScored, Blockaden/Captchas,
Timeouts oder wenn der Server zum Spielende nicht lief. Größere Ausfälle (Neustart, Deploy, Wartung) werden ebenfalls
vom Catch-up abgefangen: beim Start lädt der erste Tick den Cache neu, danach holt der Catch-up alle beendeten Spiele
der letzten 14 Tage nach (25 pro Stunde).

## Neustart / Ausfall

- Alle Zustände stehen in der DB (`match_sync_state`); der Cache ist nur eine Kopie und wird beim Start
  (Bootstrap bzw. erster Tick) und nach jedem Lauf mit Scraping neu geladen.
- Verpasste Prematch-Fenster werden nicht nachgeholt (Aufstellungen vor dem Spiel sind dann vorbei), alles nach dem
  Spiel schon: Post-Match-Polling bis Anpfiff + 6 h, danach Catch-up (14 Tage zurück), Daily-Sync (Statusänderungen).
- Fehlgeschlagene Versuche stehen in `match_sync_state` (`attempts`, `last_attempt_at`, `last_error`).

## Ein Browser, ein Prozess: Sperren

- **Ein Browser pro Prozess**: `WhoScoredClient` hält einen prozessweiten Lock. Der Tick öffnet ihn mit
  `lock_timeout=0` (belegt → Lauf wird übersprungen, nächster Tick in 3 min); Daily/Catch-up/Bootstrap warten bis zu
  600 s. `BrowserBusyError` wird geloggt und führt nie zu einem Fehlerzustand.
- **Ein Prozess pro Datenbank**: Bei PostgreSQL hält jeder Lauf einen Session-Advisory-Lock
  (`pg_try_advisory_lock`, `scraper_db_lock` in `football_jobs.py`) auf einer eigenen Verbindung. So scrapen ein
  lokaler CLI-/Worker-Prozess und die Render-Instanz nie gleichzeitig gegen dieselbe DB; wer den Lock nicht bekommt,
  überspringt den Lauf. Bei SQLite ist das ein No-op. Hinweis: Session-Locks funktionieren nicht über einen
  Transaction-Pooler (pgbouncer); bei Neon dafür die direkte (nicht gepoolte) Verbindung nutzen.
- Pro Spiel isoliert: Ein Fehler bei einem Spiel/Monat stoppt die anderen nicht; jede Funktion des Service
  committet selbst und rollt nur das betroffene Spiel zurück.

## Aktivieren

| Variable | Wirkung |
|---|---|
| `ENABLE_SCHEDULER=true` | startet den Scheduler beim App-Start (F1-Jobs + ggf. Fußball-Jobs) |
| `WHOSCORED_ENABLED=true` | registriert die Fußball-Jobs (Standard: `true`; `false` = keine Fußball-Jobs) |
| `WHOSCORED_LEAGUES=GER-Bundesliga,...` | Wettbewerbe, die synchronisiert werden (Schlüssel aus `football_competitions.py`) |
| `WHOSCORED_LOCK_TIMEOUT_SECONDS` | Standard-Wartezeit auf den Browser-Lock (Jobs setzen eigene Werte: Tick 0 s, Rest 600 s) |

Pro Wettbewerb gilt dieselbe Logik; zusätzliche Ligen erhöhen die Seitenzahl (jeder Wettbewerb hat eigene
Fixture-Monate), nicht die Zahl paralleler Browser.

## Kosten / Neon-Free-Kontingent

Neon Free bietet 100 CU-Stunden pro Monat; die Compute-Instanz skaliert nach 5 Minuten Inaktivität auf null
(Minimum 0,25 CU). Ein Job, der alle 3 Minuten die DB abfragt, würde sie dauerhaft wach halten (~186 CU-h/Monat) und
das Kontingent sprengen. Deshalb gilt:

- **Der Tick liest die DB nicht.** Er entscheidet aus einem In-Memory-Spielplan-Cache (Spiele mit Anpfiff in
  `[jetzt-14 d, jetzt+8 d]`, leichtgewichtige Einträge mit Status und Sync-Zeitstempeln, thread-sicher). Ist nichts
  fällig, gibt es **0 SQL-Statements und keinen Browser** (per Test abgesichert).
- Der Catch-up entscheidet ebenfalls zuerst aus dem Cache und berührt DB/Browser nur bei fehlenden Details
  (`attempts < 8`) oder überfälligen Spielen.
- Die DB wird nur gelesen: im Daily-Sync (04:00, einziger unbedingter Zugriff pro Tag), beim Bootstrap/ersten Tick
  nach dem Start und nach einem Lauf, der tatsächlich gescrapt hat (eine billige Neuabfrage).
- Folge: Die DB wacht nur um Spielfenster herum auf (Prematch, Post-Match, Catch-up für Nachzügler) und schläft
  dazwischen ein.

**Grobe Schätzung:** Die Bundesliga hat grob 25 Stunden Spielfenster pro Woche (inkl. Prematch/Post-Match-Puffer,
Wake-up-Nachlaufzeit 5 min). Das ergibt ca. **25–30 CU-h/Monat** (bei 0,25 CU Minimum ≈ 7–8 CU-h pro Monat reine
Rechenzeit, plus Skalierung/Nachlauf und Daily-Sync) für die Fußball-Jobs – deutlich unter 100 CU-h. Weitere Ligen
mit überlappenden Spielzeiten erhöhen den Wert nur anteilig.

**Mögliche Optimierung (nicht umgesetzt):** Der F1-Job `hourly_f1_data_fetch` fragt jede Stunde die DB ab
(~24 Wake-ups/Tag, jeweils mit 5 min Nachlauf ≈ 15+ CU-h/Monat). Er könnte ebenfalls aus einem Cache entscheiden
(z. B. nur in Rennwochenenden aktiv) oder nur zu Zeiten laufen, in denen Sessions beendet sein können. Der
F1-Code wurde bewusst nicht angepasst.
