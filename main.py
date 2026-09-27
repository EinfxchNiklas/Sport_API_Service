from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.logging_config import configure_logging
from app.api.v1.router import api_router
from app.schedulers.scheduler import start_scheduler, shutdown_scheduler
from app.web import STATIC_DIR
from app.web.router import web_router

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.enable_scheduler:
        start_scheduler()
    yield
    if settings.enable_scheduler:
        shutdown_scheduler()


app = FastAPI(
    title="Sport Dashboard API",
    version="0.2.0",
    description="Zentrale REST-API für Sportdaten (Bundesliga, F1, NFL).",
    lifespan=lifespan,
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.session_secret,
    session_cookie="admin_session",
    same_site="lax",
    https_only=settings.app_env == "production",
)

app.include_router(api_router, prefix="/api/v1")
app.include_router(web_router)
app.mount("/admin/static", StaticFiles(directory=str(STATIC_DIR)), name="admin-static")
