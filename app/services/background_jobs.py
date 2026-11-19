"""Kleiner In-Process-Runner für langlaufende Admin-Jobs (z. B. WhoScored-Importe).

Das Scrapen dauert Minuten und hält eine einzelne Browser-Sperre. Die Jobs laufen
daher in einem Daemon-Thread mit eigener DB-Session; der Status wird nur im Speicher
gehalten (geht bei einem Neustart verloren – bewusst ohne eigene Tabelle).
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo

from app.database.session import SessionLocal
from app.logging_config import get_logger

logger = get_logger(__name__)

BERLIN = ZoneInfo("Europe/Berlin")
ACTIVE_STATUSES = ("queued", "running")
_MAX_JOBS = 200

_lock = threading.Lock()
_jobs: dict[str, dict] = {}
_threads: dict[str, threading.Thread] = {}


class JobConflictError(RuntimeError):
    """Es läuft bereits ein Job derselben Gruppe."""


def _now() -> datetime:
    return datetime.now(BERLIN)


def _set(job_id: str, **fields: Any) -> None:
    with _lock:
        _jobs[job_id].update(fields)


def _run(job_id: str, fn: Callable, kwargs: dict) -> None:
    _set(job_id, status="running", started_at=_now())
    db = SessionLocal()
    try:
        result = fn(db=db, **kwargs)
        _set(job_id, status="success", result=result, finished_at=_now())
    except Exception as exc:
        logger.warning("Hintergrund-Job %s fehlgeschlagen", job_id, exc_info=True)
        _set(job_id, status="error", error=str(exc), finished_at=_now())
    finally:
        db.close()


def _prune() -> None:
    """Begrenzt den Speicher: älteste beendete Jobs entfernen (Lock muss gehalten werden)."""
    excess = len(_jobs) - _MAX_JOBS
    if excess <= 0:
        return
    finished = [jid for jid, j in _jobs.items() if j["status"] not in ACTIVE_STATUSES]
    for jid in finished[:excess]:
        _jobs.pop(jid, None)
        _threads.pop(jid, None)


def _start(name: str, fn: Callable, group: str | None, kwargs: dict) -> str:
    job_id = uuid.uuid4().hex[:12]
    with _lock:
        if group is not None and any(
            j["group"] == group and j["status"] in ACTIVE_STATUSES for j in _jobs.values()
        ):
            raise JobConflictError(f"Es läuft bereits ein Job der Gruppe '{group}'")
        _jobs[job_id] = {
            "id": job_id,
            "name": name,
            "group": group,
            "status": "queued",
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
            "created_at": _now(),
        }
        _prune()
        thread = threading.Thread(
            target=_run, args=(job_id, fn, kwargs), name=f"job-{job_id}", daemon=True
        )
        _threads[job_id] = thread
    thread.start()
    return job_id


def submit(name: str, fn: Callable, **kwargs: Any) -> str:
    """Startet ``fn(db=<eigene Session>, **kwargs)`` im Hintergrund und liefert die Job-ID."""
    return _start(name, fn, None, kwargs)


def submit_exclusive(group: str, name: str, fn: Callable, **kwargs: Any) -> str:
    """Wie ``submit``, lehnt aber mit ``JobConflictError`` ab, solange ein Job der Gruppe läuft."""
    return _start(name, fn, group, kwargs)


def has_active(group: str) -> bool:
    with _lock:
        return any(j["group"] == group and j["status"] in ACTIVE_STATUSES for j in _jobs.values())


def list_jobs(limit: int = 50) -> list[dict]:
    """Jobs, neueste zuerst."""
    with _lock:
        jobs = [dict(j) for j in _jobs.values()]
    jobs.sort(key=lambda j: j["created_at"], reverse=True)
    return jobs[:limit]


def get_job(job_id: str) -> dict | None:
    with _lock:
        job = _jobs.get(job_id)
        return dict(job) if job else None


def wait(job_id: str, timeout: float | None = None) -> None:
    """Wartet auf das Ende eines Jobs (hauptsächlich für Tests)."""
    thread = _threads.get(job_id)
    if thread is not None:
        thread.join(timeout)


def clear() -> None:
    """Verwirft alle gespeicherten Jobs (für Tests)."""
    with _lock:
        _jobs.clear()
        _threads.clear()
