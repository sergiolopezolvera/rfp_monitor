from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.services.export_service import export_opportunities_to_excel
from app.web.dependencies import get_db, get_flash, templates
from app.web.queries import get_opportunity_detail, list_filter_options, list_opportunities_page


router = APIRouter()


@router.get("/opportunities")
def opportunities_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    closing_from: date | None = Query(default=None),
    closing_to: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    filters = list_filter_options(db)
    opportunity_page = list_opportunities_page(
        db,
        page=page,
        source_name=source,
        status=status,
        fit_result=fit_result,
        closing_from=closing_from,
        closing_to=closing_to,
    )
    return templates.TemplateResponse(
        request=request,
        name="opportunities.html",
        context={
            "page_data": opportunity_page,
            "filters": filters,
            "current_filters": {
                "source": source or "",
                "status": status or "",
                "fit_result": fit_result or "",
                "closing_from": closing_from.isoformat() if closing_from else "",
                "closing_to": closing_to.isoformat() if closing_to else "",
            },
            "export_filters": {
                "created_from": "",
                "created_to": "",
                "closing_after": "",
            },
            "this_week": {
                "start": week_start.isoformat(),
                "end": today.isoformat(),
            },
            "flash": get_flash(request),
            "active_nav": "opportunities",
        },
    )


@router.get("/opportunities/export")
def export_opportunities(
    created_from: date | None = Query(default=None),
    created_to: date | None = Query(default=None),
    closing_after: date | None = Query(default=None),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    result = export_opportunities_to_excel(
        db,
        created_from=created_from,
        created_to=created_to,
        closing_after=closing_after,
        source_name=source,
        status=status,
        fit_result=fit_result,
    )
    return FileResponse(
        result.output_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=result.output_path.name,
    )


@router.get("/opportunities/{opportunity_id}")
def opportunity_detail(request: Request, opportunity_id: int, db: Session = Depends(get_db)):
    opportunity = get_opportunity_detail(db, opportunity_id)
    if opportunity is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")

    latest_analysis = max(opportunity.analyses, key=lambda item: item.id, default=None)
    return templates.TemplateResponse(
        request=request,
        name="opportunity_detail.html",
        context={
            "opportunity": opportunity,
            "latest_analysis": latest_analysis,
            "flash": get_flash(request),
            "active_nav": "opportunities",
        },
    )
