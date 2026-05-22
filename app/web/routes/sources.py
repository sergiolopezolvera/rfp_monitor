from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.web.actions import get_source_action_config, run_source_action
from app.web.dependencies import get_db, get_flash, templates
from app.web.queries import list_sources_with_counts


router = APIRouter()


@router.get("/sources")
def sources_page(request: Request, db: Session = Depends(get_db)):
    sources = list_sources_with_counts(db)
    action_configs = {source.name: get_source_action_config(source.name) for source in sources}
    return templates.TemplateResponse(
        request=request,
        name="sources.html",
        context={
            "sources": sources,
            "action_configs": action_configs,
            "flash": get_flash(request),
            "active_nav": "sources",
        },
    )


@router.post("/sources/{source_name}/actions/{action}")
def run_action(
    request: Request,
    source_name: str,
    action: str,
    limit: int = Form(default=10),
    pages: int = Form(default=5),
    db: Session = Depends(get_db),
):
    try:
        value = pages if source_name == "chiefs_of_ontario" and action == "ingest_feed" else limit
        message, level = run_source_action(db, source_name, action, value)
    except Exception as exc:
        message = f"{source_name.replace('_', ' ')}: {exc}"
        level = "error"

    query_string = urlencode({"message": message, "level": level})
    return RedirectResponse(url=f"/sources?{query_string}", status_code=303)
