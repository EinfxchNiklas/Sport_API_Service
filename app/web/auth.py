from __future__ import annotations

from fastapi import Request

from app.config import settings

ADMIN_SESSION_KEY = "is_admin"


def is_logged_in(request: Request) -> bool:
    return bool(request.session.get(ADMIN_SESSION_KEY))


def log_in(request: Request) -> None:
    request.session[ADMIN_SESSION_KEY] = True


def log_out(request: Request) -> None:
    request.session.pop(ADMIN_SESSION_KEY, None)


def check_admin_key(key: str | None) -> bool:
    return bool(key) and key == settings.admin_api_key
