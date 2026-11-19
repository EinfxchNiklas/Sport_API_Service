"""WhoScored-Datenquelle über die Bibliothek ``soccerdata`` (Selenium/Chrome).

Wichtige Eigenschaften:

* Pro Prozess darf nur EIN Browser laufen: ``WHOSCORED_BROWSER_LOCK`` wird beim Betreten des
  Clients (``with WhoScoredClient(...) as client``) gehalten und beim Schließen freigegeben.
* ``soccerdata`` wird erst beim ersten echten Seitenabruf importiert (Import-Seiteneffekte:
  legt Verzeichnisse an und ersetzt per ``dictConfig`` die Root-Logger-Handler).
* Der Browser startet LAZY beim ersten Abruf. Jede Seite wird gezielt über ``ws.get(...,
  filepath=None, no_cache=True)`` geladen – es werden nur die angeforderten Seiten gescrapt
  (kein Cache, keine Komplett-Schedule-Läufe).
* Die Rückgabewerte werden von den reinen Parsern in ``whoscored_parsers`` erzeugt.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

from lxml import html as lxml_html

from app.config import settings
from app.services.datasources.whoscored_parsers import (
    parse_fixture,
    parse_match_centre,
    parse_missing_players_html,
)

logger = logging.getLogger(__name__)

WHOSCORED_BASE_URL = "https://www.whoscored.com"
MATCH_CENTRE_VAR = "require.config.params['args'].matchCentreData"

# Genau ein Browser pro Prozess.
WHOSCORED_BROWSER_LOCK = threading.Lock()


class WhoScoredError(RuntimeError):
    """Fehler beim Abruf/Parsen von WhoScored-Daten."""


class BrowserBusyError(RuntimeError):
    """Der WhoScored-Browser wird bereits von einem anderen Client benutzt."""


def _create_whoscored(league_key: str, seasons: list[str] | None) -> Any:
    """Erzeugt die soccerdata-``WhoScored``-Instanz (startet sofort Chrome).

    Import und Browserstart passieren bewusst erst hier (lazy).
    """
    data_dir = settings.whoscored_data_dir
    if data_dir:
        os.environ.setdefault("SOCCERDATA_DIR", data_dir)

    import soccerdata as sd  # noqa: PLC0415 – Seiteneffekte, siehe Modul-Docstring

    # soccerdata ersetzt beim Import die Root-Logger-Konfiguration -> unsere wieder setzen.
    from app.logging_config import configure_logging  # noqa: PLC0415

    configure_logging(settings.log_level)

    kwargs: dict[str, Any] = {
        "leagues": league_key,
        "seasons": seasons,
        "headless": settings.whoscored_headless,
        "no_cache": True,
        "no_store": True,
    }
    if settings.whoscored_browser_path:
        kwargs["path_to_browser"] = Path(settings.whoscored_browser_path)
    if data_dir:
        kwargs["data_dir"] = Path(data_dir)
    return sd.WhoScored(**kwargs)


_SEASON_PAIR_RE = re.compile(r"(\d{4})\s*[/-]\s*(\d{4}|\d{2})")
_SEASON_SINGLE_RE = re.compile(r"^\d{4}$")


def normalize_season_code(value: str) -> str:
    """'2026/2027' | '2026-27' | '2627' -> '2627'; Einzeljahr '2022' -> '2022'."""
    text = str(value).strip()
    match = _SEASON_PAIR_RE.search(text)
    if match:
        return f"{match.group(1)[2:]}{match.group(2)[-2:]}"
    if _SEASON_SINGLE_RE.match(text):
        return text
    raise WhoScoredError(f"Ungültiger Saison-Code: {value!r}")


def _id_from_url(url: str, segment: str) -> int | None:
    match = re.search(rf"/{segment}/(\d+)", url or "", re.IGNORECASE)
    return int(match.group(1)) if match else None


class WhoScoredClient:
    """Context-Manager um einen (lazy gestarteten) soccerdata-WhoScored-Browser."""

    def __init__(
        self,
        league_key: str = "GER-Bundesliga",
        seasons: list[str] | None = None,
        lock_timeout: float | None = None,
    ):
        self.league_key = league_key
        self.seasons = seasons
        self.lock_timeout = (
            float(settings.whoscored_lock_timeout_seconds) if lock_timeout is None else float(lock_timeout)
        )
        self.pages_loaded = 0
        self._ws: Any = None
        self._lock_held = False

    # -- Lock / Lebenszyklus -------------------------------------------------

    def _acquire(self) -> None:
        if self._lock_held:
            return
        if self.lock_timeout <= 0:
            acquired = WHOSCORED_BROWSER_LOCK.acquire(blocking=False)
        else:
            acquired = WHOSCORED_BROWSER_LOCK.acquire(timeout=self.lock_timeout)
        if not acquired:
            raise BrowserBusyError(
                "WhoScored-Browser ist belegt (anderer Sync-Lauf aktiv); "
                f"Wartezeit {self.lock_timeout:.0f}s überschritten"
            )
        self._lock_held = True

    def __enter__(self) -> "WhoScoredClient":
        self._acquire()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Beendet den Browser (falls gestartet) und gibt den Lock frei. Mehrfachaufruf ist sicher."""
        ws, self._ws = self._ws, None
        try:
            if ws is not None:
                driver = getattr(ws, "_driver", None)
                if driver is not None:
                    try:
                        driver.quit()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("WhoScored-Browser konnte nicht sauber beendet werden: %s", exc)
                logger.info("WhoScored-Browser beendet (%d Seiten geladen)", self.pages_loaded)
        finally:
            if self._lock_held:
                self._lock_held = False
                WHOSCORED_BROWSER_LOCK.release()

    def _ensure_browser(self) -> Any:
        self._acquire()
        if self._ws is None:
            started = time.monotonic()
            try:
                self._ws = _create_whoscored(self.league_key, self.seasons)
            except Exception as exc:  # noqa: BLE001
                raise WhoScoredError(f"WhoScored-Browser konnte nicht gestartet werden: {exc}") from exc
            logger.info("WhoScored-Browser gestartet (%.1fs)", time.monotonic() - started)
        return self._ws

    # -- Seitenabruf ---------------------------------------------------------

    @staticmethod
    def _use_plain_get(ws: Any) -> None:
        """Nutzt Seleniums normales ``driver.get`` statt seleniumbase' ``uc_special_open_if_cf``.

        Letzteres macht vorab einen ``requests``-Aufruf; WhoScored beantwortet diesen für
        ``/Matches/...`` mit 403, woraufhin seleniumbase einen Tab-Wechsel mit Chromedriver-
        Reconnect versucht, der unter Windows beim zweiten Aufruf scheitert (~2 min Hänger).
        """
        driver = getattr(ws, "_driver", None)
        plain_get = getattr(driver, "default_get", None)
        if driver is not None and plain_get is not None and driver.get != plain_get:
            driver.get = plain_get

    def _get(self, url: str, var: str | None = None) -> bytes:
        ws = self._ensure_browser()
        if getattr(ws, "_driver", None) is None:
            raise WhoScoredError("WhoScored-Browser nicht verfügbar (Chrome-Start fehlgeschlagen)")
        self._use_plain_get(ws)
        started = time.monotonic()
        try:
            data = ws.get(url, filepath=None, no_cache=True, var=var).read()
        except Exception as exc:  # noqa: BLE001
            raise WhoScoredError(f"Seite konnte nicht geladen werden: {url} ({exc})") from exc
        self.pages_loaded += 1
        logger.debug("WhoScored-Seite geladen: %s (%d Bytes, %.1fs)", url, len(data), time.monotonic() - started)
        return data

    def _get_json(self, url: str, var: str | None = None) -> Any:
        data = self._get(url, var=var)
        try:
            return json.loads(data)
        except ValueError as exc:
            raise WhoScoredError(f"Keine gültige JSON-Antwort von {url}") from exc

    def _get_html(self, url: str) -> Any:
        data = self._get(url)
        try:
            return lxml_html.fromstring(data.decode("utf-8", errors="replace"))
        except Exception as exc:  # noqa: BLE001
            raise WhoScoredError(f"Keine gültige HTML-Antwort von {url}") from exc

    # -- Öffentliche Abrufe --------------------------------------------------

    def fetch_available_competitions(self) -> list[dict]:
        """Alle Wettbewerbe der Startseite (``allRegions``).

        Rückgabe: ``[{"ws_region_id", "region", "ws_tournament_id", "tournament", "region_type", "sort_order"}]``
        """
        regions = self._get_json(WHOSCORED_BASE_URL, var="allRegions")
        if not isinstance(regions, list) or not regions:
            raise WhoScoredError("allRegions auf der WhoScored-Startseite nicht gefunden")
        result: list[dict] = []
        for region in regions:
            for tournament in region.get("tournaments") or []:
                result.append(
                    {
                        "ws_region_id": int(region["id"]),
                        "region": region.get("name"),
                        "ws_tournament_id": int(tournament["id"]),
                        "tournament": tournament.get("name"),
                        "region_type": region.get("type"),
                        "sort_order": tournament.get("sortOrder"),
                    }
                )
        return result

    def _resolve_league(self, ws_region_id: int | None, ws_tournament_id: int | None) -> tuple[dict, dict]:
        """Liefert (region, competition) mit IDs und Namen anhand allRegions."""
        competitions = self.fetch_available_competitions()
        if ws_region_id is None or ws_tournament_id is None:
            ws = self._ensure_browser()
            selected = getattr(ws, "_selected_leagues", {}) or {}
            label = selected.get(self.league_key)
            if not label or " - " not in label:
                raise WhoScoredError(f"Liga {self.league_key!r} ist bei soccerdata nicht bekannt")
            region_name, tournament_name = label.split(" - ", 1)
            for entry in competitions:
                if entry["region"] == region_name and entry["tournament"] == tournament_name:
                    ws_region_id, ws_tournament_id = entry["ws_region_id"], entry["ws_tournament_id"]
                    break
            else:
                raise WhoScoredError(f"Wettbewerb {label!r} nicht in der WhoScored-Liste gefunden")
        for entry in competitions:
            if entry["ws_region_id"] == ws_region_id and entry["ws_tournament_id"] == ws_tournament_id:
                return (
                    {"ws_region_id": entry["ws_region_id"], "name": entry["region"]},
                    {"ws_tournament_id": entry["ws_tournament_id"], "name": entry["tournament"]},
                )
        raise WhoScoredError(f"Wettbewerb {ws_region_id}/{ws_tournament_id} nicht in der WhoScored-Liste")

    def fetch_season_metadata(
        self,
        season_code: str,
        ws_region_id: int | None = None,
        ws_tournament_id: int | None = None,
    ) -> dict:
        """Region, Wettbewerb, Saison-ID und Stages einer Saison (z. B. ``"2627"``).

        Ohne ``ws_region_id``/``ws_tournament_id`` wird der Wettbewerb aus ``league_key``
        (soccerdata-Liga-Dict) aufgelöst; mit IDs funktioniert jeder WhoScored-Wettbewerb.
        Lädt 3 Seiten (Startseite, Turnierseite, Saisonseite).

        Rückgabe: ``{"region": {"ws_region_id", "name"}, "competition": {"ws_tournament_id", "name"},
        "season": {"ws_season_id", "code"}, "stages": [{"ws_stage_id", "name", "is_default"}]}``
        """
        wanted = normalize_season_code(season_code)
        region, competition = self._resolve_league(ws_region_id, ws_tournament_id)
        region_id, tournament_id = region["ws_region_id"], competition["ws_tournament_id"]

        tournament_tree = self._get_html(f"{WHOSCORED_BASE_URL}/Regions/{region_id}/Tournaments/{tournament_id}")
        season_id: int | None = None
        for option in tournament_tree.xpath("//select[@id='seasons']/option"):
            try:
                code = normalize_season_code(option.text_content())
            except WhoScoredError:
                continue
            if code == wanted:
                season_id = _id_from_url(option.get("value") or "", "Seasons")
                break
        if season_id is None:
            raise WhoScoredError(f"Saison {wanted} für Wettbewerb {region_id}/{tournament_id} nicht gefunden")

        season_tree = self._get_html(
            f"{WHOSCORED_BASE_URL}/Regions/{region_id}/Tournaments/{tournament_id}/Seasons/{season_id}"
        )
        stages: list[dict] = []
        fixtures_links = season_tree.xpath("//a[text()='Fixtures']/@href")
        default_stage_id = _id_from_url(fixtures_links[0], "Stages") if fixtures_links else None
        if default_stage_id is not None:
            stages.append({"ws_stage_id": default_stage_id, "name": None, "is_default": True})
        for option in season_tree.xpath("//select[contains(@id,'stages')]/option"):
            stage_id = _id_from_url(option.get("value") or "", "Stages")
            if stage_id is None:
                continue
            name = (option.text_content() or "").strip() or None
            existing = next((s for s in stages if s["ws_stage_id"] == stage_id), None)
            if existing is not None:
                existing["name"] = name
            else:
                stages.append({"ws_stage_id": stage_id, "name": name, "is_default": False})
        if not stages:
            raise WhoScoredError(f"Keine Stages für Saison {wanted} ({season_id}) gefunden")

        return {
            "region": region,
            "competition": competition,
            "season": {"ws_season_id": season_id, "code": wanted},
            "stages": stages,
        }

    def fetch_calendar_months(
        self,
        ws_region_id: int,
        ws_tournament_id: int,
        ws_season_id: int,
        ws_stage_id: int,
    ) -> list[tuple[int, int]]:
        """Monate mit Spielen als ``(jahr, monat)`` (Monat 1–12), aufsteigend sortiert.

        WhoScored liefert ``wsCalendar.mask`` als ``{jahr: {monat0: {tag: 1}}}`` mit 0-basierten Monaten.
        """
        url = (
            f"{WHOSCORED_BASE_URL}/Regions/{ws_region_id}/Tournaments/{ws_tournament_id}"
            f"/Seasons/{ws_season_id}/Stages/{ws_stage_id}"
        )
        calendar = self._get_json(url, var="wsCalendar")
        if not isinstance(calendar, dict) or not isinstance(calendar.get("mask"), dict):
            raise WhoScoredError(f"Kalender (wsCalendar) nicht gefunden: {url}")
        months: set[tuple[int, int]] = set()
        for year, month_map in calendar["mask"].items():
            for month0 in month_map:
                months.add((int(year), int(month0) + 1))
        return sorted(months)

    def fetch_fixtures_month(self, ws_stage_id: int, year: int, month: int) -> list[dict]:
        """Spiele einer Stage in einem Monat (``month`` 1–12), geparst via ``parse_fixture``."""
        url = f"{WHOSCORED_BASE_URL}/tournaments/{ws_stage_id}/data/?d={year}{month:02d}"
        data = self._get_json(url)
        if not isinstance(data, dict) or not isinstance(data.get("tournaments"), list):
            raise WhoScoredError(f"Unerwartetes Fixture-Format: {url}")
        fixtures: dict[int, dict] = {}
        for tournament in data["tournaments"]:
            for raw in tournament.get("matches") or []:
                try:
                    fixture = parse_fixture(raw)
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("WhoScored-Fixture übersprungen (%s): %s", raw.get("id"), exc)
                    continue
                fixtures[fixture["ws_match_id"]] = fixture
        return list(fixtures.values())

    def fetch_match_centre(self, ws_match_id: int) -> dict | None:
        """Match-Centre-Daten (geparst) oder ``None``, wenn WhoScored (noch) keine liefert."""
        raw = self._get_json(f"{WHOSCORED_BASE_URL}/Matches/{ws_match_id}/Live", var=MATCH_CENTRE_VAR)
        try:
            return parse_match_centre(raw)
        except ValueError as exc:
            raise WhoScoredError(f"Match Centre {ws_match_id} nicht parsebar: {exc}") from exc

    def fetch_missing_players(self, ws_match_id: int) -> dict:
        """Fehlende Spieler aus der Preview-Seite: ``{"home": [...], "away": [...]}``."""
        data = self._get(f"{WHOSCORED_BASE_URL}/Matches/{ws_match_id}/Preview")
        try:
            return parse_missing_players_html(data.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise WhoScoredError(f"Preview {ws_match_id} ungültig: {exc}") from exc
