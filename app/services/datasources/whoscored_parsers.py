"""Reine Parser für WhoScored-Rohdaten (kein soccerdata-/Selenium-Import, kein Netzwerk).

Alle Funktionen sind deterministisch und arbeiten nur auf bereits geladenen
JSON-/HTML-Daten. Zeitstempel werden als tz-aware ``datetime`` in Berliner Zeit
(``Europe/Berlin``) geliefert.

Beobachtungen aus echten WhoScored-Daten (Bundesliga 2026/27, Stand 11/2026):

* Fixture-Feed (``/tournaments/{stage}/data/?d=YYYYMM``): ``tournaments[*].matches[*]``.
  Es gibt KEINEN Spieltag/Runden-Wert in den Daten.
* ``startTimeUtc`` ist die verlässliche Anstoßzeit (UTC); ``startTime`` ist naiv.
* ``status`` ist numerisch (1 = angesetzt, 6 = beendet), ``elapsed`` ein Text
  ("", "FT", "HT", "AET", "PEN", "Post", "Can", "Abd", "Susp", "ET1", "ET2" oder
  die gespielte Minute), ``period`` ein interner Perioden-Code (0 = vor Anpfiff,
  7 = Ende).
* ``matchCentreData`` ist ``null`` für noch nicht gestartete Spiele.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo

from lxml import html as lxml_html

BERLIN_TZ = ZoneInfo("Europe/Berlin")

# ---------------------------------------------------------------------------
# Statistik-Aggregation
# ---------------------------------------------------------------------------

# Verhältnis-/Prozentwerte: aus den gespeicherten Zählwerten ableitbar -> nicht speichern (3NF).
DERIVED_STAT_KEYS: frozenset[str] = frozenset(
    {
        "passSuccess",       # passesAccurate / passesTotal
        "aerialSuccess",     # aerialsWon / aerialsTotal
        "dribbleSuccess",    # dribblesWon / dribblesAttempted
        "tackleSuccess",     # tackleSuccessful / tacklesTotal
        "throwInAccuracy",   # throwInsAccurate / throwInsTotal
    }
)

# Weitere Schlüssel, die nie als Zahlen-Statistik gespeichert werden.
EXCLUDED_STAT_KEYS: frozenset[str] = DERIVED_STAT_KEYS | frozenset(
    {
        "minutesWithStats",  # Liste der Minuten mit Daten (keine Statistik)
    }
)

# Schlüssel, bei denen nicht die Summe, sondern der Wert der höchsten Minute gilt.
LAST_VALUE_STAT_KEYS: frozenset[str] = frozenset({"ratings"})


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def aggregate_stat(key: str, per_minute: Any) -> float | None:
    """Aggregiert eine WhoScored-Minuten-Statistik zu einem Einzelwert.

    WhoScored liefert Statistiken als ``{minute: wert}``-Dict. Regeln:

    * Zählwerte (Pässe, Schüsse, Tackles, Berührungen, ...): Summe aller Minutenwerte.
    * ``ratings`` (Spielernote bzw. Team-Rating): Wert der höchsten Minute
      (= letzte/endgültige Bewertung).
    * Ausgeschlossene Schlüssel (``EXCLUDED_STAT_KEYS``, v. a. Prozentwerte): ``None``.
    * Kein Dict, leeres Dict oder keine numerischen Werte: ``None``.

    Hinweis: Die Team-``possession`` wird hier als Summe der Minutenwerte
    aggregiert; der Ballbesitz-Anteil (%) entsteht erst in ``parse_match_centre``
    im Verhältnis zum Gegner.
    """
    if key in EXCLUDED_STAT_KEYS:
        return None
    if not isinstance(per_minute, dict) or not per_minute:
        return None
    values: list[tuple[int, float]] = []
    for minute, value in per_minute.items():
        if not _is_number(value):
            continue
        try:
            values.append((int(minute), float(value)))
        except (TypeError, ValueError):
            continue
    if not values:
        return None
    if key in LAST_VALUE_STAT_KEYS:
        return max(values, key=lambda item: item[0])[1]
    return float(sum(value for _, value in values))


def _aggregate_stats(stats: Any, *, skip: frozenset[str] = frozenset()) -> dict[str, float]:
    result: dict[str, float] = {}
    if not isinstance(stats, dict):
        return result
    for key, per_minute in stats.items():
        if key in skip or key in LAST_VALUE_STAT_KEYS:
            continue
        value = aggregate_stat(key, per_minute)
        if value is not None:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _clean_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def parse_utc_to_berlin(value: Any) -> datetime | None:
    """ISO-8601-Zeitstempel (UTC, optional mit 'Z') -> tz-aware Berliner Zeit."""
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(BERLIN_TZ)


_SCORE_RE = re.compile(r"^\s*(\d+)\s*:\s*(\d+)\s*$")


def _parse_score_string(value: Any) -> tuple[int | None, int | None]:
    """'2 : 1' -> (2, 1); leer/ungültig -> (None, None)."""
    if not isinstance(value, str):
        return None, None
    match = _SCORE_RE.match(value)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# 'elapsed'-Texte (kleingeschrieben) -> Status. Die Texte stammen aus dem
# 'localization'-Block des Fixture-Feeds (ft, aet, pen, ht, et1, et2, post, can, abd, susp).
_ELAPSED_FINISHED = frozenset({"ft", "aet", "pen"})
_ELAPSED_POSTPONED = frozenset({"post", "susp"})
_ELAPSED_CANCELLED = frozenset({"can"})
_ELAPSED_ABANDONED = frozenset({"abd"})

# Numerischer 'status' des Fixture-Feeds (nur diese beiden Werte live beobachtet).
_STATUS_SCHEDULED = 1
_STATUS_FINISHED = 6


def map_fixture_status(status_code: Any, elapsed: Any) -> str:
    """Bildet WhoScored-``status``/``elapsed`` auf unsere Status-Werte ab.

    Reihenfolge (erste passende Regel gewinnt):

    1. ``elapsed`` = FT / AET / PEN            -> ``finished``
    2. ``elapsed`` = Post / Susp               -> ``postponed`` (Susp = unterbrochen, ggf. später fortgesetzt)
    3. ``elapsed`` = Can                       -> ``cancelled``
    4. ``elapsed`` = Abd                       -> ``abandoned``
    5. ``status`` = 6                          -> ``finished``
    6. ``status`` = 1 und ``elapsed`` leer     -> ``scheduled``
    7. ``elapsed`` nicht leer (HT, ET1, ET2, Minute) -> ``live``
    8. sonst                                   -> ``scheduled``

    Live beobachtet wurden nur ``status`` 1 (``elapsed`` "") und 6 (``elapsed`` "FT").
    Die übrigen Texte stammen aus dem Localization-Block des Feeds und sind
    nicht an echten Spielen verifiziert.
    """
    elapsed_text = str(elapsed).strip().lower() if elapsed is not None else ""
    if elapsed_text in _ELAPSED_FINISHED:
        return "finished"
    if elapsed_text in _ELAPSED_POSTPONED:
        return "postponed"
    if elapsed_text in _ELAPSED_CANCELLED:
        return "cancelled"
    if elapsed_text in _ELAPSED_ABANDONED:
        return "abandoned"
    code = _to_int(status_code)
    if code == _STATUS_FINISHED:
        return "finished"
    if code == _STATUS_SCHEDULED and not elapsed_text:
        return "scheduled"
    if elapsed_text:
        return "live"
    return "scheduled"


def _parse_fixture_team(raw: dict, prefix: str) -> dict:
    team_id = _to_int(raw.get(f"{prefix}TeamId"))
    if team_id is None:
        raise ValueError(f"Fixture ohne {prefix}TeamId: {raw.get('id')}")
    return {
        "ws_team_id": team_id,
        "name": _clean_str(raw.get(f"{prefix}TeamName")) or "",
        "country_code": _clean_str(raw.get(f"{prefix}TeamCountryCode")),
        "country_name": _clean_str(raw.get(f"{prefix}TeamCountryName")),
    }


def parse_fixture(raw: dict) -> dict:
    """Parst ein Roh-Match aus dem Monats-Fixture-Feed.

    Raises:
        ValueError: wenn Match-ID oder Team-IDs fehlen.
    """
    match_id = _to_int(raw.get("id"))
    if match_id is None:
        raise ValueError("Fixture ohne Match-ID")
    kickoff = parse_utc_to_berlin(raw.get("startTimeUtc"))
    if kickoff is None:
        # Fallback: 'startTime' ist naiv; der Feed liefert timezoneOffset 0 -> als UTC behandeln.
        kickoff = parse_utc_to_berlin(raw.get("startTime"))
    elapsed = raw.get("elapsed")
    return {
        "ws_match_id": match_id,
        "ws_stage_id": _to_int(raw.get("stageId")),
        "kickoff_time": kickoff,
        "status": map_fixture_status(raw.get("status"), elapsed),
        "home": _parse_fixture_team(raw, "home"),
        "away": _parse_fixture_team(raw, "away"),
        "home_score": _to_int(raw.get("homeScore")),
        "away_score": _to_int(raw.get("awayScore")),
        "et_home_score": _to_int(raw.get("homeExtratimeScore")),
        "et_away_score": _to_int(raw.get("awayExtratimeScore")),
        "pen_home_score": _to_int(raw.get("homePenaltyScore")),
        "pen_away_score": _to_int(raw.get("awayPenaltyScore")),
        "started_at": parse_utc_to_berlin(raw.get("startedAtUtc")),
        "first_half_ended_at": parse_utc_to_berlin(raw.get("firstHalfEndedAtUtc")),
        "second_half_started_at": parse_utc_to_berlin(raw.get("secondHalfStartedAtUtc")),
        "is_lineup_confirmed": _to_bool(raw.get("isLineupConfirmed")),
        "has_preview": _to_bool(raw.get("hasPreview")),
        # Zusätzliche Schlüssel (nicht Teil des Basis-Vertrags)
        "elapsed": _clean_str(elapsed),
        "ws_status_code": _to_int(raw.get("status")),
    }


# ---------------------------------------------------------------------------
# Match Centre
# ---------------------------------------------------------------------------

_FINISHED_STATUS_CODE = 6
_FINISHED_ELAPSED = frozenset({"ft", "aet", "pen"})


def _parse_referee(raw: Any) -> dict | None:
    if not isinstance(raw, dict):
        return None
    official_id = _to_int(raw.get("officialId"))
    if official_id is None:
        return None
    first_name = _clean_str(raw.get("firstName"))
    last_name = _clean_str(raw.get("lastName"))
    name = _clean_str(raw.get("name")) or " ".join(p for p in (first_name, last_name) if p)
    return {
        "ws_official_id": official_id,
        "first_name": first_name,
        "last_name": last_name,
        "name": name,
    }


def _parse_formations(raw_formations: Any) -> list[dict]:
    result: list[dict] = []
    for formation in raw_formations or []:
        if not isinstance(formation, dict):
            continue
        player_ids = formation.get("playerIds") or []
        slots = formation.get("formationSlots") or []
        raw_positions = formation.get("formationPositions") or []
        positions: list[dict] = []
        for index, position in enumerate(raw_positions):
            slot = index + 1
            player_id = None
            if slot in slots:
                slot_index = slots.index(slot)
                if slot_index < len(player_ids):
                    player_id = _to_int(player_ids[slot_index])
            positions.append(
                {
                    "slot": slot,
                    "ws_player_id": player_id,
                    "vertical": _to_float(position.get("vertical")) if isinstance(position, dict) else None,
                    "horizontal": _to_float(position.get("horizontal")) if isinstance(position, dict) else None,
                }
            )
        result.append(
            {
                "name": _clean_str(formation.get("formationName")) or "",
                "period": _to_int(formation.get("period")),
                "start_minute": _to_int(formation.get("startMinuteExpanded")) or 0,
                "end_minute": _to_int(formation.get("endMinuteExpanded")),
                "captain_ws_player_id": _to_int(formation.get("captainPlayerId")),
                "positions": positions,
            }
        )
    return result


def _display_name(value: Any) -> str | None:
    if isinstance(value, dict):
        return _clean_str(value.get("displayName"))
    return None


def _qualifier_names(event: dict) -> set[str]:
    names: set[str] = set()
    for qualifier in event.get("qualifiers") or []:
        if isinstance(qualifier, dict):
            name = _display_name(qualifier.get("type"))
            if name:
                names.add(name)
    return names


_CARD_TYPES = {"Yellow": "yellow", "SecondYellow": "second_yellow", "Red": "red"}


def _parse_incidents(raw_events: Any, team_id: int, opponent_team_id: int | None) -> list[dict]:
    """Nur Tore und Karten aus ``incidentEvents`` (keine Wechsel, keine Koordinaten).

    * Tor:       ``type`` = Goal; Qualifier ``OwnGoal`` -> own_goal, ``Penalty`` -> penalty_goal.
    * Eigentor:  Das Event gehört zum Team des Spielers (``ws_team_id`` = Team des Eigentor-Schützen);
                 gutgeschrieben wird das Tor dem Gegner (``credited_ws_team_id``).
    * Karte:     ``type`` = Card mit ``cardType`` Yellow / SecondYellow / Red.
    * ``ws_event_id`` = globale Event-``id`` (int64, > 2^31!). ``ws_event_number`` = ``eventId`` (laufende Nr.).
    * ``minute`` = rohe WhoScored-Minute (nullbasiert; Anzeige i. d. R. +1, bei Nachspielzeit
      45+5 -> 50). ``minute_label`` = Anzeigetext (z. B. "45+5").
    * ``related_ws_player_id`` nur bei Toren (Vorbereiter); bei Karten immer ``None``.
    """
    result: list[dict] = []
    for event in raw_events or []:
        if not isinstance(event, dict):
            continue
        type_name = _display_name(event.get("type"))
        event_id = _to_int(event.get("id"))
        if event_id is None:
            continue
        minute = _to_int(event.get("minute"))
        if minute is None:
            continue
        qualifiers = _qualifier_names(event)
        minute_info = event.get("minuteInfo") if isinstance(event.get("minuteInfo"), dict) else {}
        base = {
            "ws_event_id": event_id,
            "ws_event_number": _to_int(event.get("eventId")),
            "ws_team_id": _to_int(event.get("teamId")) or team_id,
            "minute": minute,
            "expanded_minute": _to_int(event.get("expandedMinute")),
            "period": _display_name(event.get("period")),
            "ws_player_id": _to_int(event.get("playerId")),
            "minute_label": _clean_str(minute_info.get("minuteString")),
        }
        if type_name == "Goal":
            if "OwnGoal" in qualifiers or event.get("isOwnGoal"):
                incident_type = "own_goal"
                credited = opponent_team_id
            elif "Penalty" in qualifiers:
                incident_type = "penalty_goal"
                credited = base["ws_team_id"]
            else:
                incident_type = "goal"
                credited = base["ws_team_id"]
            result.append(
                {
                    **base,
                    "type": incident_type,
                    "card_type": None,
                    "related_ws_player_id": _to_int(event.get("relatedPlayerId")),
                    "credited_ws_team_id": credited,
                }
            )
        elif type_name == "Card":
            card_type = _CARD_TYPES.get(_display_name(event.get("cardType")) or "")
            if card_type is None:
                continue
            result.append(
                {
                    **base,
                    "type": "card",
                    "card_type": card_type,
                    "related_ws_player_id": None,
                    "credited_ws_team_id": None,
                }
            )
    return result


def _sub_minutes(raw_events: Any) -> dict[int, dict[str, int]]:
    """Rohe Minute der Wechsel je Spieler aus SubstitutionOn/-Off-Events."""
    minutes: dict[int, dict[str, int]] = {}
    for event in raw_events or []:
        if not isinstance(event, dict):
            continue
        type_name = _display_name(event.get("type"))
        if type_name not in ("SubstitutionOn", "SubstitutionOff"):
            continue
        player_id = _to_int(event.get("playerId"))
        minute = _to_int(event.get("minute"))
        if player_id is None or minute is None:
            continue
        minutes.setdefault(player_id, {})["in" if type_name == "SubstitutionOn" else "out"] = minute
    return minutes


def _parse_players(raw_players: Any, raw_events: Any) -> list[dict]:
    sub_minutes = _sub_minutes(raw_events)
    result: list[dict] = []
    for player in raw_players or []:
        if not isinstance(player, dict):
            continue
        player_id = _to_int(player.get("playerId"))
        if player_id is None:
            continue
        stats = player.get("stats")
        rating = aggregate_stat("ratings", stats.get("ratings")) if isinstance(stats, dict) else None
        sub = sub_minutes.get(player_id, {})
        result.append(
            {
                "ws_player_id": player_id,
                "name": _clean_str(player.get("name")) or "",
                "shirt_no": _to_int(player.get("shirtNo")),
                "position": _clean_str(player.get("position")),
                "height": _to_int(player.get("height")),
                "weight": _to_int(player.get("weight")),
                "age": _to_int(player.get("age")),
                "is_first_eleven": bool(player.get("isFirstEleven", False)),
                "is_man_of_the_match": bool(player.get("isManOfTheMatch", False)),
                "rating": rating,
                "subbed_in_minute": sub.get("in"),
                "subbed_out_minute": sub.get("out"),
                "stats": _aggregate_stats(stats),
                # Zusätzliche Schlüssel (nicht Teil des Basis-Vertrags)
                "subbed_in_expanded_minute": _to_int(player.get("subbedInExpandedMinute")),
                "subbed_out_expanded_minute": _to_int(player.get("subbedOutExpandedMinute")),
            }
        )
    return result


def _parse_team_block(raw: Any, opponent_team_id: int | None) -> dict:
    if not isinstance(raw, dict) or _to_int(raw.get("teamId")) is None:
        raise ValueError("Match-Centre-Team ohne teamId")
    team_id = int(raw["teamId"])
    raw_events = raw.get("incidentEvents")
    return {
        "ws_team_id": team_id,
        "name": _clean_str(raw.get("name")) or "",
        "country_name": _clean_str(raw.get("countryName")),
        "manager_name": _clean_str(raw.get("managerName")),
        "average_age": _to_float(raw.get("averageAge")),
        # 'ratings' (Team-Rating) und Ballbesitz-Anteil werden unten bzw. separat gesetzt.
        "stats": _aggregate_stats(raw.get("stats")),
        "rating": aggregate_stat("ratings", (raw.get("stats") or {}).get("ratings"))
        if isinstance(raw.get("stats"), dict)
        else None,
        "players": _parse_players(raw.get("players"), raw_events),
        "formations": _parse_formations(raw.get("formations")),
        "incidents": _parse_incidents(raw_events, team_id, opponent_team_id),
    }


def _stat_sum(team_raw: dict, key: str) -> float | None:
    stats = team_raw.get("stats") if isinstance(team_raw, dict) else None
    if not isinstance(stats, dict):
        return None
    per_minute = stats.get(key)
    if not isinstance(per_minute, dict):
        return None
    values = [float(v) for v in per_minute.values() if _is_number(v)]
    return sum(values) if values else None


def parse_match_centre(raw: dict | None) -> dict | None:
    """Parst ``matchCentreData`` eines Spiels.

    Gibt ``None`` zurück, wenn ``raw`` leer/``None`` ist (Spiel noch ohne Match-Centre-Daten:
    ``matchCentreData`` ist bei nicht gestarteten Spielen ``null``).

    ``is_finished``: ``statusCode`` == 6 **oder** ``elapsed`` in {FT, AET, PEN}.

    Team-Statistiken (``stats``): Summe der Minutenwerte (Zählwerte); ``possession`` ist der
    Ballbesitz-Anteil in Prozent (0–100, eine Nachkommastelle) = Summe Eigenwert / (Summe Eigen- +
    Gegnerwert); fehlt ein Gegnerwert, entfällt der Schlüssel. ``ratings`` steht nicht in ``stats``
    (Spieler: ``rating``).

    Raises:
        ValueError: wenn die Struktur (home/away mit teamId) nicht passt.
    """
    if not raw or not isinstance(raw, dict):
        return None
    raw_home = raw.get("home")
    raw_away = raw.get("away")
    if not isinstance(raw_home, dict) or not isinstance(raw_away, dict):
        raise ValueError("matchCentreData ohne home/away")

    home_id = _to_int(raw_home.get("teamId"))
    away_id = _to_int(raw_away.get("teamId"))
    home = _parse_team_block(raw_home, away_id)
    away = _parse_team_block(raw_away, home_id)

    home_poss = _stat_sum(raw_home, "possession")
    away_poss = _stat_sum(raw_away, "possession")
    for block, own, other in ((home, home_poss, away_poss), (away, away_poss, home_poss)):
        block["stats"].pop("possession", None)
        if own is not None and other is not None and (own + other) > 0:
            block["stats"]["possession"] = round(100.0 * own / (own + other), 1)

    ht_home, ht_away = _parse_score_string(raw.get("htScore"))
    ft_home, ft_away = _parse_score_string(raw.get("ftScore"))
    et_home, et_away = _parse_score_string(raw.get("etScore"))
    pen_home, pen_away = _parse_score_string(raw.get("pkScore"))

    elapsed = str(raw.get("elapsed") or "").strip().lower()
    is_finished = _to_int(raw.get("statusCode")) == _FINISHED_STATUS_CODE or elapsed in _FINISHED_ELAPSED
    has_lineups = any(p["is_first_eleven"] for p in home["players"] + away["players"])

    return {
        "venue_name": _clean_str(raw.get("venueName")),
        "attendance": _to_int(raw.get("attendance")),
        "referee": _parse_referee(raw.get("referee")),
        "ht_home_score": ht_home,
        "ht_away_score": ht_away,
        "ft_home_score": ft_home,
        "ft_away_score": ft_away,
        "et_home_score": et_home,
        "et_away_score": et_away,
        "pen_home_score": pen_home,
        "pen_away_score": pen_away,
        "is_finished": is_finished,
        "has_lineups": has_lineups,
        "home": home,
        "away": away,
        # Zusätzliche Schlüssel (nicht Teil des Basis-Vertrags)
        "elapsed": _clean_str(raw.get("elapsed")),
        "ws_status_code": _to_int(raw.get("statusCode")),
    }


# ---------------------------------------------------------------------------
# Preview: fehlende Spieler
# ---------------------------------------------------------------------------

def _class_xpath(token: str) -> str:
    return f"contains(concat(' ', normalize-space(@class), ' '), ' {token} ')"


def _parse_missing_table(container: Any) -> list[dict]:
    players: list[dict] = []
    if container is None:
        return players
    for row in container.xpath(".//table/tbody/tr"):
        links = row.xpath("./td[contains(@class,'pn')]/a")
        if not links:
            continue
        link = links[0]
        href = link.get("href") or ""
        parts = href.split("/")
        try:
            player_id = int(parts[2])
        except (IndexError, ValueError):
            continue
        reason_nodes = row.xpath("./td[contains(@class,'reason')]/span")
        reason = _clean_str(reason_nodes[0].get("title")) if reason_nodes else None
        status_nodes = row.xpath("./td[contains(@class,'confirmed')]")
        status = _clean_str(status_nodes[0].text_content()) if status_nodes else None
        players.append(
            {
                "ws_player_id": player_id,
                "name": _clean_str(link.text_content()) or "",
                "reason": reason,
                "status": status,
            }
        )
    return players


def parse_missing_players_html(html: str) -> dict:
    """Parst die 'Missing Players'-Tabellen der Preview-Seite (``/Matches/{id}/Preview``).

    Rückgabe: ``{"home": [...], "away": [...]}`` mit ``ws_player_id``, ``name``, ``reason``
    (``injured`` / ``unfit`` / ``suspended`` ...) und ``status`` (``Out`` / ``Doubtful`` ...).

    Gültige Preview-Seite = enthält ``#match-header`` oder ``#preview``. Ist der Block
    ``#missing-players`` leer oder fehlt er auf einer gültigen Seite, werden leere Listen geliefert.

    Raises:
        ValueError: wenn die Seite keine gültige Match-Preview ist (z. B. "The page you requested
            does not exist", Sperrseite oder leerer Inhalt) – damit Aufrufer keine Daten löschen.
    """
    if not html or not isinstance(html, str) or not html.strip():
        raise ValueError("Leere Preview-Seite")
    try:
        tree = lxml_html.fromstring(html)
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"Preview-Seite nicht parsebar: {exc}") from exc

    if not tree.xpath("//div[@id='match-header'] | //*[@id='preview']"):
        raise ValueError("Keine gültige Match-Preview-Seite")

    containers = tree.xpath("//div[@id='missing-players']")
    if not containers:
        return {"home": [], "away": []}
    container = containers[0]

    home_nodes = container.xpath(f"./div[{_class_xpath('home')}]") or container.xpath("./div[2]")
    away_nodes = container.xpath(f"./div[{_class_xpath('away')}]") or container.xpath("./div[3]")
    return {
        "home": _parse_missing_table(home_nodes[0] if home_nodes else None),
        "away": _parse_missing_table(away_nodes[0] if away_nodes else None),
    }
