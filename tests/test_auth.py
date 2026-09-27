import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import require_admin
from app.config import settings


def _fake_request(session: dict | None = None) -> Request:
    scope = {"type": "http", "headers": [], "method": "GET", "path": "/", "query_string": b""}
    if session is not None:
        scope["session"] = session
    return Request(scope)


def test_require_admin_valid_key():
    result = require_admin(request=_fake_request(), x_api_key=settings.admin_api_key)
    assert result is None


def test_require_admin_wrong_key():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request=_fake_request(), x_api_key="wrong-key")
    assert exc_info.value.status_code == 401


def test_require_admin_no_key():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request=_fake_request(), x_api_key=None)
    assert exc_info.value.status_code == 401


def test_require_admin_valid_session_cookie():
    result = require_admin(request=_fake_request(session={"is_admin": True}), x_api_key=None)
    assert result is None


def test_require_admin_no_key_no_session():
    with pytest.raises(HTTPException) as exc_info:
        require_admin(request=_fake_request(session={}), x_api_key=None)
    assert exc_info.value.status_code == 401
