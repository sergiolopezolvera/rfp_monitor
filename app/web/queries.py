from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased, selectinload

from app.models import LLMAnalysis, Opportunity, ScrapeRun, Source

PAGE_SIZE = 25


@dataclass(frozen=True)
class DashboardStats:
    total_opportunities: int
    by_source: list[tuple[str, int]]
    by_status: list[tuple[str, int]]
    analyzed_count: int
    unanalyzed_count: int
    fit_score_counts: list[tuple[int | None, int]]
    closing_soon: list[Opportunity]


@dataclass(frozen=True)
class SourceListRow:
    id: int
    name: str
    base_url: str | None
    is_active: bool
    opportunity_count: int
    analyzed_count: int
    status_counts: list[tuple[str, int]]
    last_scrape_run: SourceRunSummary | None
    last_fetch_run: SourceRunSummary | None


@dataclass(frozen=True)
class SourceRunSummary:
    status: str
    run_at: datetime | None
    requested_value: int | None
    requested_unit: str | None
    items_found: int
    items_inserted: int
    items_updated: int
    items_failed: int


@dataclass(frozen=True)
class OpportunityListRow:
    opportunity: Opportunity
    source: Source
    latest_analysis: LLMAnalysis | None


@dataclass(frozen=True)
class OpportunityPage:
    items: list[OpportunityListRow]
    page: int
    page_size: int
    total_items: int
    total_pages: int


def _latest_analysis_join():
    latest_analysis_sq = (
        select(
            LLMAnalysis.opportunity_id.label("opportunity_id"),
            func.max(LLMAnalysis.id).label("latest_analysis_id"),
        )
        .group_by(LLMAnalysis.opportunity_id)
        .subquery()
    )
    latest_analysis = aliased(LLMAnalysis)
    return latest_analysis_sq, latest_analysis


def get_dashboard_stats(db: Session) -> DashboardStats:
    latest_analysis_sq, latest_analysis = _latest_analysis_join()
    today = date.today()
    soon_cutoff = today + timedelta(days=14)

    total_opportunities = db.scalar(select(func.count(Opportunity.id))) or 0

    by_source = list(
        db.execute(
            select(Source.name, func.count(Opportunity.id))
            .select_from(Source)
            .outerjoin(Opportunity, Opportunity.source_id == Source.id)
            .group_by(Source.id, Source.name)
            .order_by(func.count(Opportunity.id).desc(), Source.name.asc())
        ).all()
    )

    by_status = list(
        db.execute(
            select(Opportunity.status, func.count(Opportunity.id))
            .group_by(Opportunity.status)
            .order_by(func.count(Opportunity.id).desc(), Opportunity.status.asc())
        ).all()
    )

    analyzed_count = db.scalar(
        select(func.count(Opportunity.id))
        .select_from(Opportunity)
        .join(latest_analysis_sq, latest_analysis_sq.c.opportunity_id == Opportunity.id)
    ) or 0
    unanalyzed_count = total_opportunities - analyzed_count

    fit_score_counts = list(
        db.execute(
            select(latest_analysis.fit_score, func.count(Opportunity.id))
            .select_from(Opportunity)
            .join(latest_analysis_sq, latest_analysis_sq.c.opportunity_id == Opportunity.id)
            .join(latest_analysis, latest_analysis.id == latest_analysis_sq.c.latest_analysis_id)
            .where(latest_analysis.fit_score.is_not(None))
            .group_by(latest_analysis.fit_score)
            .order_by(latest_analysis.fit_score.desc())
        ).all()
    )

    closing_soon = list(
        db.scalars(
            select(Opportunity)
            .options(selectinload(Opportunity.source))
            .where(
                Opportunity.closing_date.is_not(None),
                Opportunity.closing_date >= today,
                Opportunity.closing_date <= soon_cutoff,
            )
            .order_by(Opportunity.closing_date.asc(), Opportunity.id.asc())
            .limit(10)
        ).all()
    )

    return DashboardStats(
        total_opportunities=total_opportunities,
        by_source=by_source,
        by_status=by_status,
        analyzed_count=analyzed_count,
        unanalyzed_count=unanalyzed_count,
        fit_score_counts=fit_score_counts,
        closing_soon=closing_soon,
    )


def list_sources_with_counts(db: Session) -> list[SourceListRow]:
    latest_analysis_sq, _ = _latest_analysis_join()
    rows = db.execute(
        select(
            Source.id,
            Source.name,
            Source.base_url,
            Source.is_active,
            func.count(func.distinct(Opportunity.id)).label("opportunity_count"),
            func.count(func.distinct(latest_analysis_sq.c.opportunity_id)).label("analyzed_count"),
        )
        .select_from(Source)
        .outerjoin(Opportunity, Opportunity.source_id == Source.id)
        .outerjoin(latest_analysis_sq, latest_analysis_sq.c.opportunity_id == Opportunity.id)
        .group_by(Source.id)
        .order_by(Source.name.asc())
    ).all()

    status_rows = db.execute(
        select(Source.id, Opportunity.status, func.count(Opportunity.id))
        .select_from(Source)
        .outerjoin(Opportunity, Opportunity.source_id == Source.id)
        .where(Opportunity.status.is_not(None))
        .group_by(Source.id, Opportunity.status)
        .order_by(Source.id.asc(), func.count(Opportunity.id).desc(), Opportunity.status.asc())
    ).all()

    status_counts_by_source: dict[int, list[tuple[str, int]]] = {}
    for source_id, status, count in status_rows:
        status_counts_by_source.setdefault(source_id, []).append((status, count))

    run_rows = db.execute(
        select(
            ScrapeRun.source_id,
            ScrapeRun.status,
            ScrapeRun.items_found,
            ScrapeRun.items_inserted,
            ScrapeRun.items_updated,
            ScrapeRun.items_failed,
            ScrapeRun.log_summary,
            ScrapeRun.finished_at,
            ScrapeRun.started_at,
        )
        .order_by(ScrapeRun.source_id.asc(), ScrapeRun.finished_at.desc().nullslast(), ScrapeRun.started_at.desc())
    ).all()

    latest_scrape_by_source: dict[int, SourceRunSummary] = {}
    latest_fetch_by_source: dict[int, SourceRunSummary] = {}

    for row in run_rows:
        summary_data: dict = {}
        if row.log_summary:
            try:
                summary_data = json.loads(row.log_summary)
            except json.JSONDecodeError:
                summary_data = {}

        action = summary_data.get("action")
        if action not in {"ingest_feed", "fetch_details"}:
            continue

        summary = SourceRunSummary(
            status=row.status,
            run_at=row.finished_at or row.started_at,
            requested_value=summary_data.get("requested_value"),
            requested_unit=summary_data.get("requested_unit"),
            items_found=row.items_found,
            items_inserted=row.items_inserted,
            items_updated=row.items_updated,
            items_failed=row.items_failed,
        )

        if action == "ingest_feed" and row.source_id not in latest_scrape_by_source:
            latest_scrape_by_source[row.source_id] = summary
        if action == "fetch_details" and row.source_id not in latest_fetch_by_source:
            latest_fetch_by_source[row.source_id] = summary

    return [
        SourceListRow(
            id=row.id,
            name=row.name,
            base_url=row.base_url,
            is_active=row.is_active,
            opportunity_count=row.opportunity_count,
            analyzed_count=row.analyzed_count,
            status_counts=status_counts_by_source.get(row.id, []),
            last_scrape_run=latest_scrape_by_source.get(row.id),
            last_fetch_run=latest_fetch_by_source.get(row.id),
        )
        for row in rows
    ]


def list_filter_options(db: Session) -> dict[str, list[str]]:
    sources = list(db.scalars(select(Source.name).order_by(Source.name.asc())).all())
    statuses = list(
        db.scalars(
            select(Opportunity.status).distinct().where(Opportunity.status.is_not(None)).order_by(Opportunity.status.asc())
        ).all()
    )
    return {"sources": sources, "statuses": statuses}


def list_opportunities_page(
    db: Session,
    *,
    page: int,
    source_name: str | None = None,
    status: str | None = None,
    fit_result: str | None = None,
    fit_level: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    closing_after: date | None = None,
) -> OpportunityPage:
    latest_analysis_sq, latest_analysis = _latest_analysis_join()
    base_stmt = (
        select(Opportunity, Source, latest_analysis)
        .join(Source, Opportunity.source_id == Source.id)
        .outerjoin(latest_analysis_sq, latest_analysis_sq.c.opportunity_id == Opportunity.id)
        .outerjoin(latest_analysis, latest_analysis.id == latest_analysis_sq.c.latest_analysis_id)
    )

    if source_name:
        base_stmt = base_stmt.where(Source.name == source_name)
    if status:
        base_stmt = base_stmt.where(Opportunity.status == status)
    if created_from:
        base_stmt = base_stmt.where(Opportunity.created_at >= datetime.combine(created_from, datetime.min.time()))
    if created_to:
        base_stmt = base_stmt.where(Opportunity.created_at < datetime.combine(created_to + timedelta(days=1), datetime.min.time()))
    if closing_after:
        base_stmt = base_stmt.where(Opportunity.closing_date >= closing_after)

    if fit_result == "fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(True))
        if fit_level == "3":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 3)
        elif fit_level == "2":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 2)
        elif fit_level == "1":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 1)
    elif fit_result == "not_fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(False))
    elif fit_result == "unanalyzed":
        base_stmt = base_stmt.where(latest_analysis.id.is_(None))

    count_stmt = select(func.count()).select_from(base_stmt.subquery())
    total_items = db.scalar(count_stmt) or 0
    total_pages = max(1, (total_items + PAGE_SIZE - 1) // PAGE_SIZE)
    current_page = min(max(page, 1), total_pages)
    offset = (current_page - 1) * PAGE_SIZE

    rows = db.execute(
        base_stmt
        .order_by(
            Opportunity.closing_date.asc().nullslast(),
            Opportunity.publication_date.desc().nullslast(),
            Opportunity.id.desc(),
        )
        .offset(offset)
        .limit(PAGE_SIZE)
    ).all()

    items = [
        OpportunityListRow(opportunity=opportunity, source=source, latest_analysis=analysis)
        for opportunity, source, analysis in rows
    ]

    return OpportunityPage(
        items=items,
        page=current_page,
        page_size=PAGE_SIZE,
        total_items=total_items,
        total_pages=total_pages,
    )


def get_opportunity_detail(db: Session, opportunity_id: int) -> Opportunity | None:
    return db.scalar(
        select(Opportunity)
        .options(selectinload(Opportunity.source), selectinload(Opportunity.analyses))
        .where(Opportunity.id == opportunity_id)
    )
