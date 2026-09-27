from fastapi import Header, HTTPException, Request, status

from app.config import settings
from app.database.session import get_db

__all__ = ["get_db"]

ADMIN_SESSION_KEY = "is_admin"


def require_admin(
    request: Request,
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> None:
    if x_api_key and x_api_key == settings.admin_api_key:
        return None
    try:
        if request.session.get(ADMIN_SESSION_KEY):
            return None
    except AssertionError:
        pass  # SessionMiddleware nicht installiert (z. B. in isolierten Unit-Tests)
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Ungültiger oder fehlender API-Key")
