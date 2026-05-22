from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401
from app.config import settings
from app.db import Base, engine, SessionLocal
from app.services.source_service import seed_default_sources
from app.web.routes.dashboard import router as dashboard_router
from app.web.routes.files import router as files_router
from app.web.routes.opportunities import router as opportunities_router
from app.web.routes.sources import router as sources_router


def create_app() -> FastAPI:
    settings.ensure_directories()
    Base.metadata.create_all(bind=engine)

    with SessionLocal() as db:
        seed_default_sources(db)


    app = FastAPI(title="RFP Monitor Dashboard")
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    app.include_router(dashboard_router)
    app.include_router(sources_router)
    app.include_router(opportunities_router)
    app.include_router(files_router)
    return app


app = create_app()
