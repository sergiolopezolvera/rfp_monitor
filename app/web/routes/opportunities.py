from datetime import date, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.services.export_service import export_opportunities_to_excel
from app.web.dependencies import get_db, get_flash, templates
from app.web.labels import fit_filter_to_params
from app.web.queries import get_opportunity_detail, list_filter_options, list_opportunities_page

router = APIRouter()


def _resolve_filters(
    *,
    fit: str | None,
    fit_result: str | None,
    fit_level: str | None,
    open_only: bool,
    closing_after: date | None,
) -> tuple[str | None, str | None, date | None]:
    """Turn the simple UI controls into the query parameters the services expect.

    ``fit`` (one dropdown) wins over the older ``fit_result``/``fit_level`` pair, and
    "only open" means "closing today or later".
    """
    if fit:
        fit_result, fit_level = fit_filter_to_params(fit)
    if open_only and closing_after is None:
        closing_after = date.today()
    return fit_result or None, fit_level or None, closing_after


@router.get("/opportunities")
def opportunities_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    fit: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    fit_level: str | None = Query(default=None),
    open_only: bool = Query(default=False),
    created_from: date | None = Query(default=None),
    created_to: date | None = Query(default=None),
    closing_after: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    resolved_fit, resolved_level, resolved_closing = _resolve_filters(
        fit=fit,
        fit_result=fit_result,
        fit_level=fit_level,
        open_only=open_only,
        closing_after=closing_after,
    )
    opportunity_page = list_opportunities_page(
        db,
        page=page,
        source_name=source,
        status=status,
        fit_result=resolved_fit,
        fit_level=resolved_level,
        created_from=created_from,
        created_to=created_to,
        closing_after=resolved_closing,
    )

    current_filters = {
        "source": source or "",
        "status": status or "",
        "fit": fit or "",
        "fit_result": fit_result or "",
        "fit_level": fit_level or "",
        "open_only": "1" if open_only else "",
        "created_from": created_from.isoformat() if created_from else "",
        "created_to": created_to.isoformat() if created_to else "",
        "closing_after": closing_after.isoformat() if closing_after else "",
    }
    filter_query = urlencode({key: value for key, value in current_filters.items() if value})

    return templates.TemplateResponse(
        request=request,
        name="opportunities.html",
        context={
            "page_data": opportunity_page,
            "filters": list_filter_options(db),
            "current_filters": current_filters,
            "filter_query": filter_query,
            "has_filters": bool(filter_query),
            "this_week": {"start": week_start.isoformat(), "end": today.isoformat()},
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
    fit: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    fit_level: str | None = Query(default=None),
    open_only: bool = Query(default=False),
    db: Session = Depends(get_db),
):
    resolved_fit, resolved_level, resolved_closing = _resolve_filters(
        fit=fit,
        fit_result=fit_result,
        fit_level=fit_level,
        open_only=open_only,
        closing_after=closing_after,
    )
    result = export_opportunities_to_excel(
        db,
        created_from=created_from,
        created_to=created_to,
        closing_after=resolved_closing,
        source_name=source,
        status=status,
        fit_result=resolved_fit,
        fit_level=resolved_level,
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
            "back_url": request.headers.get("referer") if "/opportunities" in request.headers.get("referer", "") else "/opportunities",
            "flash": get_flash(request),
            "active_nav": "opportunities",
        },
    )
