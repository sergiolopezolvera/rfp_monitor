import re

with open("app/web/routes/opportunities.py", "r") as f:
    content = f.read()

old_opp_page = """@router.get("/opportunities")
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
    )"""

new_opp_page = """@router.get("/opportunities")
def opportunities_page(
    request: Request,
    page: int = Query(default=1, ge=1),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    fit_level: str | None = Query(default=None),
    created_from: date | None = Query(default=None),
    created_to: date | None = Query(default=None),
    closing_after: date | None = Query(default=None),
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
        fit_level=fit_level,
        created_from=created_from,
        created_to=created_to,
        closing_after=closing_after,
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
                "fit_level": fit_level or "",
                "created_from": created_from.isoformat() if created_from else "",
                "created_to": created_to.isoformat() if created_to else "",
                "closing_after": closing_after.isoformat() if closing_after else "",
            },
            "this_week": {
                "start": week_start.isoformat(),
                "end": today.isoformat(),
            },
            "flash": get_flash(request),
            "active_nav": "opportunities",
        },
    )"""

content = content.replace(old_opp_page, new_opp_page)


old_export = """@router.get("/opportunities/export")
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
    )"""

new_export = """@router.get("/opportunities/export")
def export_opportunities(
    created_from: date | None = Query(default=None),
    created_to: date | None = Query(default=None),
    closing_after: date | None = Query(default=None),
    source: str | None = Query(default=None),
    status: str | None = Query(default=None),
    fit_result: str | None = Query(default=None),
    fit_level: str | None = Query(default=None),
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
        fit_level=fit_level,
    )"""

content = content.replace(old_export, new_export)

with open("app/web/routes/opportunities.py", "w") as f:
    f.write(content)
