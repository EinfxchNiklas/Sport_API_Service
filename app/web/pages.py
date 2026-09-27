from __future__ import annotations

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.web import TEMPLATES_DIR
from app.web.auth import check_admin_key, is_logged_in, log_in, log_out

router = APIRouter(include_in_schema=False)
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=303)


@router.get("/admin/login")
def login_page(request: Request):
    if is_logged_in(request):
        return RedirectResponse(url="/admin", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"error": None})


@router.post("/admin/login")
def login_submit(request: Request, api_key: str = Form(...)):
    if not check_admin_key(api_key):
        return templates.TemplateResponse(
            request, "login.html", {"error": "Ungültiger API-Key"}, status_code=401
        )
    log_in(request)
    return RedirectResponse(url="/admin", status_code=303)


@router.post("/admin/logout")
def logout(request: Request):
    log_out(request)
    return _redirect_to_login()


@router.get("/admin")
def dashboard(request: Request):
    if not is_logged_in(request):
        return _redirect_to_login()
    return templates.TemplateResponse(request, "dashboard.html", {"active": "dashboard"})


@router.get("/admin/schedulers")
def schedulers_page(request: Request):
    if not is_logged_in(request):
        return _redirect_to_login()
    return templates.TemplateResponse(request, "schedulers.html", {"active": "schedulers"})


@router.get("/admin/architecture")
def architecture_page(request: Request):
    if not is_logged_in(request):
        return _redirect_to_login()
    return templates.TemplateResponse(request, "architecture.html", {"active": "architecture"})


@router.get("/admin/endpoints")
def endpoints_page(request: Request):
    if not is_logged_in(request):
        return _redirect_to_login()
    return templates.TemplateResponse(request, "endpoints.html", {"active": "endpoints"})
