"""Registry der unterstützten WhoScored-Wettbewerbe.

Die IDs wurden live gegen WhoScored geprüft. Der ``league_key`` ist unser interner Schlüssel
(angelehnt an soccerdata); die WhoScored-IDs werden IMMER explizit übergeben, damit auch
Wettbewerbe funktionieren, die soccerdata selbst nicht kennt (z. B. DFB-Pokal).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import settings

logger = logging.getLogger(__name__)

BERLIN_TZ = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class CompetitionConfig:
    league_key: str
    ws_region_id: int
    ws_tournament_id: int
    name: str
    slug: str
    # "league" | "cup" | "tournament"
    format: str
    region_name: str
    # Monat, in dem die neue Saison beginnt (Europa: Juli)
    season_start_month: int = 7


COMPETITIONS: dict[str, CompetitionConfig] = {
    cfg.league_key: cfg
    for cfg in (
        CompetitionConfig("GER-Bundesliga", 81, 3, "Bundesliga", "bundesliga", "league", "Germany"),
        CompetitionConfig("GER-2. Bundesliga", 81, 6, "2. Bundesliga", "2-bundesliga", "league", "Germany"),
        CompetitionConfig("GER-DFB-Pokal", 81, 24, "DFB-Pokal", "dfb-pokal", "cup", "Germany"),
        CompetitionConfig(
            "INT-Champions League", 250, 12, "Champions League", "champions-league", "tournament", "Europe"
        ),
        CompetitionConfig("INT-Europa League", 250, 30, "Europa League", "europa-league", "tournament", "Europe"),
        CompetitionConfig(
            "INT-Conference League", 250, 715, "Conference League", "conference-league", "tournament", "Europe"
        ),
        CompetitionConfig("ENG-Premier League", 252, 2, "Premier League", "premier-league", "league", "England"),
        CompetitionConfig("ESP-La Liga", 206, 4, "LaLiga", "la-liga", "league", "Spain"),
        CompetitionConfig("ITA-Serie A", 108, 5, "Serie A", "serie-a", "league", "Italy"),
        CompetitionConfig("FRA-Ligue 1", 74, 22, "Ligue 1", "ligue-1", "league", "France"),
    )
}


def get_competition_config(league_key: str) -> CompetitionConfig:
    """Liefert die Konfiguration zu ``league_key`` (ValueError mit allen gültigen Schlüsseln)."""
    try:
        return COMPETITIONS[league_key]
    except KeyError:
        valid = ", ".join(sorted(COMPETITIONS))
        raise ValueError(f"Unbekannter league_key {league_key!r}. Gültige Schlüssel: {valid}") from None


def enabled_competitions() -> list[CompetitionConfig]:
    """Aktive Wettbewerbe aus ``settings.whoscored_league_list`` (unbekannte Schlüssel werden übersprungen)."""
    result: list[CompetitionConfig] = []
    for key in settings.whoscored_league_list:
        config = COMPETITIONS.get(key)
        if config is None:
            logger.warning("Unbekannter Wettbewerb in WHOSCORED_LEAGUES ignoriert: %r", key)
            continue
        result.append(config)
    return result


def current_season_code(now: datetime | None = None, start_month: int = 7) -> str:
    """Saison-Code (z. B. ``"2627"``) zum Zeitpunkt ``now`` (Standard: jetzt, Berliner Zeit).

    Ab ``start_month`` gilt die im laufenden Jahr gestartete Saison, davor die des Vorjahres.
    """
    if now is None:
        now = datetime.now(BERLIN_TZ)
    start_year = now.year if now.month >= start_month else now.year - 1
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"
