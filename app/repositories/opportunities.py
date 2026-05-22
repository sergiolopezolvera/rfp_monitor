from datetime import datetime

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from app.models import Opportunity


def get_opportunity_by_source_and_url(
    db: Session,
    *,
    source_id: int,
    url: str,
) -> Opportunity | None:
    stmt = select(Opportunity).where(
        Opportunity.source_id == source_id,
        Opportunity.url == url,
    )
    return db.scalar(stmt)


def list_opportunities(
    db: Session,
    *,
    source_id: int | None = None,
    status: str | None = None,
    limit: int = 100,
) -> list[Opportunity]:
    stmt = select(Opportunity).order_by(Opportunity.created_at.desc())

    if source_id is not None:
        stmt = stmt.where(Opportunity.source_id == source_id)

    if status is not None:
        stmt = stmt.where(Opportunity.status == status)

    stmt = stmt.limit(limit)

    return list(db.scalars(stmt).all())


def create_opportunity(
    db: Session,
    *,
    source_id: int,
    url: str,
    title: str | None = None,
    description_raw: str | None = None,
    organization: str | None = None,
    location: str | None = None,
    publication_date=None,
    closing_date=None,
    notice_type: str | None = None,
    category: str | None = None,
    raw_html_path: str | None = None,
    raw_text_path: str | None = None,
    hash_content: str | None = None,
    status: str = "new",
    source_record_id: str | None = None,
) -> Opportunity:
    opportunity = Opportunity(
        source_id=source_id,
        source_record_id=source_record_id,
        url=url,
        title=title,
        description_raw=description_raw,
        organization=organization,
        location=location,
        publication_date=publication_date,
        closing_date=closing_date,
        notice_type=notice_type,
        category=category,
        raw_html_path=raw_html_path,
        raw_text_path=raw_text_path,
        hash_content=hash_content,
        status=status,
    )
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def get_or_create_opportunity(
    db: Session,
    *,
    source_id: int,
    url: str,
    **kwargs,
) -> tuple[Opportunity, bool]:
    existing = get_opportunity_by_source_and_url(
        db,
        source_id=source_id,
        url=url,
    )
    if existing is not None:
        return existing, False

    created = create_opportunity(
        db,
        source_id=source_id,
        url=url,
        **kwargs,
    )
    return created, True


def update_opportunity(
    db: Session,
    opportunity: Opportunity,
    **fields,
) -> Opportunity:
    """Update an opportunity with provided fields."""
    for key, value in fields.items():
        setattr(opportunity, key, value)

    opportunity.updated_at = datetime.utcnow()
    db.add(opportunity)
    db.commit()
    db.refresh(opportunity)
    return opportunity


def list_opportunities_for_detail_fetch(
    db: Session,
    *,
    source_id: int,
    limit: int = 20,
    include_statuses: tuple[str, ...] = ("discovered", "detail_error", "detail_blocked"),
    retry_error_after_minutes: int = 60,
    retry_blocked_after_minutes: int = 360,
) -> list[Opportunity]:
    """Return opportunities that need or may benefit from detail-page processing."""
    now = datetime.utcnow()
    retry_error_before = now.timestamp() - (retry_error_after_minutes * 60)
    retry_blocked_before = now.timestamp() - (retry_blocked_after_minutes * 60)

    retry_error_cutoff = datetime.fromtimestamp(retry_error_before)
    retry_blocked_cutoff = datetime.fromtimestamp(retry_blocked_before)

    eligibility_filters = []

    if "discovered" in include_statuses:
        eligibility_filters.append(Opportunity.status == "discovered")
    if "detail_error" in include_statuses:
        eligibility_filters.append(
            (Opportunity.status == "detail_error") & (Opportunity.updated_at <= retry_error_cutoff)
        )
    if "detail_blocked" in include_statuses:
        eligibility_filters.append(
            (Opportunity.status == "detail_blocked") & (Opportunity.updated_at <= retry_blocked_cutoff)
        )
    if "detail_fetched" in include_statuses:
        eligibility_filters.append(Opportunity.status == "detail_fetched")

    if not eligibility_filters:
        return []

    stmt = (
        select(Opportunity)
        .where(
            Opportunity.source_id == source_id,
            or_(*eligibility_filters),
        )
        .order_by(
            case(
                (Opportunity.status == "discovered", 0),
                (Opportunity.status == "detail_error", 1),
                (Opportunity.status == "detail_blocked", 2),
                else_=3,
            ),
            Opportunity.updated_at.asc(),
            Opportunity.created_at.asc(),
        )
        .limit(limit)
    )
    return list(db.scalars(stmt).all())
