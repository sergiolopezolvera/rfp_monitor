from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
from datetime import datetime

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.db import SessionLocal


WEB_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
templates.env.globals["artifact_url"] = lambda path: f"/artifacts?{urlencode({'path': path})}"
templates.env.filters["datetime_local"] = lambda value: value.strftime("%Y-%m-%d %H:%M") if isinstance(value, datetime) else ""


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def get_flash(request: Request) -> dict[str, str | None]:
    return {
        "message": request.query_params.get("message"),
        "level": request.query_params.get("level", "info"),
    }
