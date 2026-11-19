"""Kommandozeile für den WhoScored-Fußballimport.

Aufruf: ``python -m app.football_cli <befehl> ...``

* ``competitions [--live]``                  – Registry (und mit ``--live`` alle WhoScored-Wettbewerbe)
* ``import-season --league KEY --season 2627 [--no-details] [--max-matches N]``
* ``sync-match --ws-match-id N [--final]``

Exit-Code 0 = Erfolg, 1 = Fehler, 2 = keine Daten verfügbar (nur ``sync-match``).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys

from app.config import settings
from app.logging_config import configure_logging

logger = logging.getLogger("football_cli")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.football_cli", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    comp = sub.add_parser("competitions", help="Registry der unterstützten Wettbewerbe anzeigen")
    comp.add_argument("--live", action="store_true", help="zusätzlich alle Wettbewerbe von WhoScored laden")

    imp = sub.add_parser("import-season", help="Saison importieren (Spielplan + Details beendeter Spiele)")
    imp.add_argument("--league", required=True, help="league_key, z. B. GER-Bundesliga")
    imp.add_argument("--season", required=True, help="Saison-Code, z. B. 2627")
    imp.add_argument("--no-details", action="store_true", help="nur Spielplan, keine Match-Details")
    imp.add_argument("--max-matches", type=int, default=None, help="maximal N Detail-Abrufe")

    sync = sub.add_parser("sync-match", help="Details eines einzelnen Spiels synchronisieren")
    sync.add_argument("--ws-match-id", type=int, required=True)
    sync.add_argument("--final", action="store_true", help="Details als endgültig markieren")
    return parser


def _cmd_competitions(args: argparse.Namespace) -> int:
    from app.services.football_competitions import COMPETITIONS

    print(f"{'league_key':<24} {'region':>6} {'turnier':>8}  {'format':<11} {'name'}")
    for cfg in COMPETITIONS.values():
        print(f"{cfg.league_key:<24} {cfg.ws_region_id:>6} {cfg.ws_tournament_id:>8}  {cfg.format:<11} {cfg.name}")
    if args.live:
        from app.services.datasources.whoscored import WhoScoredClient

        with WhoScoredClient() as client:
            available = client.fetch_available_competitions()
        print(f"\nWhoScored: {len(available)} Wettbewerbe")
        for entry in available:
            print(
                f"{entry['ws_region_id']:>6} {entry['ws_tournament_id']:>8}  "
                f"{entry['region']} - {entry['tournament']}"
            )
    return 0


def _cmd_import_season(args: argparse.Namespace) -> int:
    from app.database.session import SessionLocal
    from app.services.football_service import import_season

    with SessionLocal() as db:
        summary = import_season(
            db,
            args.league,
            args.season,
            with_details=not args.no_details,
            max_matches=args.max_matches,
        )
    print(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return 1 if summary["details"]["errors"] else 0


def _cmd_sync_match(args: argparse.Namespace) -> int:
    from app.database.session import SessionLocal
    from app.services.football_service import sync_match_by_ws_id

    with SessionLocal() as db:
        result = sync_match_by_ws_id(db, args.ws_match_id, final=args.final)
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
    if result["status"] == "ok":
        return 0
    return 2 if result["status"] == "unavailable" else 1


_COMMANDS = {
    "competitions": _cmd_competitions,
    "import-season": _cmd_import_season,
    "sync-match": _cmd_sync_match,
}


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    configure_logging(settings.log_level)
    try:
        return _COMMANDS[args.command](args)
    except KeyboardInterrupt:
        logger.error("Abgebrochen")
        return 130
    except Exception as exc:  # noqa: BLE001 – CLI: Fehler melden, Exit-Code != 0
        logger.error("%s: %s", type(exc).__name__, exc)
        logger.debug("Details", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
