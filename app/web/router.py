from __future__ import annotations

from fastapi import APIRouter

from app.web.api import router as api_router
from app.web.pages import router as pages_router

web_router = APIRouter()
web_router.include_router(pages_router)
web_router.include_router(api_router)
