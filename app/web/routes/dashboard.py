from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.web.dependencies import get_db, get_flash, templates
from app.web.queries import get_dashboard_stats


router = APIRouter()


@router.get("/")
@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context={
            "stats": get_dashboard_stats(db),
            "flash": get_flash(request),
            "active_nav": "dashboard",
        },
    )
