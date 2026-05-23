import json
from datetime import datetime

from sqlalchemy.orm import Session

from app.logger import logger
from app.models import ScrapeRun
from app.parsers.bidsandtenders_parser import parse_bidsandtenders_notice
from app.parsers.canadabuys_parser import parse_canadabuys_notice
from app.parsers.chiefsofontario_parser import parse_chiefs_of_ontario_notice
from app.parsers.merx_parser import parse_merx_notice
from app.parsers.nationtalk_parser import parse_nationtalk_notice
from app.parsers.ontariotenders_parser import parse_ontario_tenders_notice
from app.repositories.opportunities import (
    get_or_create_opportunity,
    list_opportunities_for_detail_fetch,
    update_opportunity,
)
from app.repositories.sources import get_source_by_name
from app.sources.bidsandtenders import BidsAndTendersConnector
from app.sources.canadabuys import CanadaBuysConnector
from app.sources.chiefsofontario import ChiefsOfOntarioConnector
from app.sources.merx import MerxConnector
from app.sources.nationtalk import NationTalkConnector
from app.sources.ontariotenders import OntarioTendersConnector
from app.utils.files import build_raw_html_path, build_raw_text_path, write_text_file
from app.utils.hashing import sha256_text


def _start_run(db: Session, *, source_id: int) -> ScrapeRun:
    run = ScrapeRun(source_id=source_id, status="started")
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def _finish_run(
    db: Session,
    run: ScrapeRun,
    *,
    status: str,
    action: str,
    requested_value: int,
    requested_unit: str,
    items_found: int,
    items_inserted: int = 0,
    items_updated: int = 0,
    items_failed: int = 0,
    extra: dict | None = None,
) -> None:
    summary = {
        "action": action,
        "requested_value": requested_value,
        "requested_unit": requested_unit,
    }
    if extra:
        summary.update(extra)

    run.status = status
    run.items_found = items_found
    run.items_inserted = items_inserted
    run.items_updated = items_updated
    run.items_failed = items_failed
    run.log_summary = json.dumps(summary, ensure_ascii=False)
    run.finished_at = datetime.utcnow()
    db.add(run)
    db.commit()


def _update_bidsandtenders_feed_metadata(db: Session, opp, item) -> bool:
    """
    Refresh an existing Bids & Tenders opportunity with the cleaner feed metadata.

    The search-results table is the canonical source for title, organization, and
    closing date because those values are more consistent than the detail page.
    """
    feed_fields = {
        "title": item.title,
        "organization": item.organization,
        "publication_date": item.date_published.date() if item.date_published else None,
        "closing_date": item.closing_date.date() if item.closing_date else None,
        "source_record_id": item.source_record_id,
    }
    changes = {
        field_name: value
        for field_name, value in feed_fields.items()
        if value is not None and getattr(opp, field_name) != value
    }

    if not changes:
        return False

    if not opp.description_raw and (item.summary or item.description):
        changes["description_raw"] = item.summary or item.description

    update_opportunity(db, opp, **changes)
    return True

def _update_ontario_tenders_feed_metadata(db: Session, opp, item) -> bool:
    feed_fields = {
        "title": item.title,
        "organization": item.organization,
        "publication_date": item.date_published.date() if item.date_published else None,
        "closing_date": item.closing_date.date() if item.closing_date else None,
        "source_record_id": item.source_record_id,
        "notice_type": item.bid_status,
        "category": item.category,
    }
    changes = {
        field_name: value
        for field_name, value in feed_fields.items()
        if value is not None and getattr(opp, field_name) != value
    }

    if not changes:
        return False

    if not opp.description_raw and (item.summary or item.description):
        changes["description_raw"] = item.summary or item.description

    update_opportunity(db, opp, **changes)
    return True



def ingest_canadabuys_feed(db: Session, limit: int = 50) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "canadabuys")
    if source is None:
        raise ValueError("Source 'canadabuys' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    connector = CanadaBuysConnector()
    try:
        items = connector.fetch_feed_items(limit=limit)

        results: list[tuple[str, bool]] = []

        for item in items:
            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                publication_date=item.date_published.date() if item.date_published else None,
                status="discovered",
            )
            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db,
            run,
            status="success",
            action="ingest_feed",
            requested_value=limit,
            requested_unit="items",
            items_found=len(items),
            items_inserted=created_count,
            items_updated=existing_count,
        )
        logger.info(
            "CanadaBuys ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(
            db,
            run,
            status="error",
            action="ingest_feed",
            requested_value=limit,
            requested_unit="items",
            items_found=0,
            items_failed=1,
        )
        raise


def fetch_canadabuys_details(
    db: Session,
    limit: int = 3,
    *,
    min_interval_seconds: float = 20.0,
    retry_wait_seconds: float = 45.0,
    retry_error_after_minutes: int = 60,
    retry_blocked_after_minutes: int = 360,
) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "canadabuys")
    if source is None:
        raise ValueError("Source 'canadabuys' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = CanadaBuysConnector(
            min_interval_seconds=min_interval_seconds,
            retry_wait_seconds=retry_wait_seconds,
        )
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error", "detail_blocked"),
            retry_error_after_minutes=retry_error_after_minutes,
            retry_blocked_after_minutes=retry_blocked_after_minutes,
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)
                parsed = parse_canadabuys_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("canadabuys", record_id)
                text_path = build_raw_text_path("canadabuys", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    title=parsed.get("title") or opp.title,
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=parsed.get("organization") or opp.organization,
                    location=parsed.get("location") or opp.location,
                    publication_date=parsed.get("publication_date") or opp.publication_date,
                    closing_date=parsed.get("closing_date") or opp.closing_date,
                    notice_type=parsed.get("notice_type") or opp.notice_type,
                    category=parsed.get("category") or opp.category,
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )
                results.append((opp.id, "updated"))
            except CanadaBuysConnector.NoticeAccessBlocked as exc:
                logger.warning(
                    "CanadaBuys notice access blocked for opportunity %s: status=%s retry_after=%s preview=%s",
                    opp.id,
                    exc.status_code,
                    exc.retry_after,
                    exc.body_preview,
                )
                update_opportunity(db, opp, status="detail_blocked")
                results.append((opp.id, "blocked"))
            except Exception as exc:
                logger.warning("Failed to fetch/process CanadaBuys detail for opportunity %s: %s", opp.id, exc)
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        blocked = sum(1 for _, status in results if status == "blocked")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db,
            run,
            status="success",
            action="fetch_details",
            requested_value=limit,
            requested_unit="items",
            items_found=len(opportunities),
            items_updated=updated,
            items_failed=blocked + errors,
            extra={"blocked": blocked, "errors": errors},
        )
        logger.info("CanadaBuys detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(
            db,
            run,
            status="error",
            action="fetch_details",
            requested_value=limit,
            requested_unit="items",
            items_found=0,
            items_failed=1,
        )
        raise


def ingest_merx_feed(db: Session, limit: int = 50) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "merx")
    if source is None:
        raise ValueError("Source 'merx' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = MerxConnector()
        items = connector.fetch_feed_items(limit=limit)

        results: list[tuple[str, bool]] = []

        for item in items:
            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                publication_date=item.date_published.date() if item.date_published else None,
                status="discovered",
            )
            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db, run, status="success", action="ingest_feed", requested_value=limit,
            requested_unit="items", items_found=len(items), items_inserted=created_count, items_updated=existing_count
        )
        logger.info(
            "MERX ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(db, run, status="error", action="ingest_feed", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise


def _is_merx_interceptor(html: str) -> bool:
    """Return True when MERX serves a login/interception page instead of notice content."""
    markers = [
        "An action is required before access to this content is granted",
        "You must Login or Sign Up",
        "interceptorLightbox",
        "Login Required",
        "subscription package",
    ]
    return any(marker in html for marker in markers)


def fetch_merx_details(db: Session, limit: int = 10) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "merx")
    if source is None:
        raise ValueError("Source 'merx' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = MerxConnector()
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error"),
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)

                if _is_merx_interceptor(html):
                    logger.warning(
                        "MERX notice is blocked by login/interceptor for opportunity %s: %s",
                        opp.id,
                        opp.url,
                    )
                    update_opportunity(db, opp, status="detail_blocked")
                    results.append((opp.id, "blocked"))
                    continue

                parsed = parse_merx_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("merx", record_id)
                text_path = build_raw_text_path("merx", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    title=opp.title or parsed.get("title"),
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=opp.organization or parsed.get("organization"),
                    location=parsed.get("location") or opp.location,
                    publication_date=parsed.get("publication_date") or opp.publication_date,
                    closing_date=parsed.get("closing_date") or opp.closing_date,
                    source_record_id=parsed.get("solicitation_number") or parsed.get("reference_number") or opp.source_record_id,
                    notice_type=parsed.get("notice_type") or opp.notice_type,
                    category=parsed.get("purchase_type") or opp.category,
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )
                results.append((opp.id, "updated"))

            except Exception as exc:
                logger.warning(
                    "Failed to fetch/process MERX detail for opportunity %s: %s",
                    opp.id,
                    exc,
                )
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        blocked = sum(1 for _, status in results if status == "blocked")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db, run, status="success", action="fetch_details", requested_value=limit,
            requested_unit="items", items_found=len(opportunities), items_updated=updated,
            items_failed=blocked + errors, extra={"blocked": blocked, "errors": errors}
        )
        logger.info("MERX detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(db, run, status="error", action="fetch_details", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise

def ingest_bidsandtenders_feed(db: Session, limit: int = 50) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "bidsandtenders")
    if source is None:
        raise ValueError("Source 'bidsandtenders' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = BidsAndTendersConnector()
        items = connector.fetch_feed_items(limit=limit)
        excluded_keywords = [
            "notice of intent",
            "participant of",
            "group purchasing",
        ]

        results: list[tuple[str, bool]] = []

        for item in items:
            title_normalized = (item.title or "").lower()

            if any(keyword in title_normalized for keyword in excluded_keywords):
                logger.info(
                    "Skipping Bids & Tenders opportunity due to title filter: %s",
                    item.title,
                )
                continue

            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                organization=item.organization,
                publication_date=item.date_published.date() if item.date_published else None,
                closing_date=item.closing_date.date() if item.closing_date else None,
                source_record_id=item.source_record_id,
                status="discovered",
            )

            if not created:
                _update_bidsandtenders_feed_metadata(db, opportunity, item)

            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db, run, status="success", action="ingest_feed", requested_value=limit,
            requested_unit="items", items_found=len(items), items_inserted=created_count, items_updated=existing_count
        )
        logger.info(
            "Bids & Tenders ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(db, run, status="error", action="ingest_feed", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise

def fetch_bidsandtenders_details(db: Session, limit: int = 10) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "bidsandtenders")
    if source is None:
        raise ValueError("Source 'bidsandtenders' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = BidsAndTendersConnector()
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error"),
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)
                parsed = parse_bidsandtenders_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("bidsandtenders", record_id)
                text_path = build_raw_text_path("bidsandtenders", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=opp.organization or parsed.get("organization"),
                    publication_date=opp.publication_date or parsed.get("publication_date"),
                    closing_date=opp.closing_date or parsed.get("closing_date"),
                    source_record_id=opp.source_record_id or parsed.get("reference_number"),
                    notice_type=parsed.get("bid_type") or opp.notice_type,
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )
                results.append((opp.id, "updated"))

            except Exception as exc:
                logger.warning(
                    "Failed to fetch/process Bids & Tenders detail for opportunity %s: %s",
                    opp.id,
                    exc,
                )
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db, run, status="success", action="fetch_details", requested_value=limit,
            requested_unit="items", items_found=len(opportunities), items_updated=updated,
            items_failed=errors, extra={"errors": errors}
        )
        logger.info("Bids & Tenders detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(db, run, status="error", action="fetch_details", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise


def ingest_ontario_tenders_feed(db: Session, limit: int = 50) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "ontario_tenders")
    if source is None:
        raise ValueError("Source 'ontario_tenders' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = OntarioTendersConnector()
        items = connector.fetch_feed_items(limit=limit)

        results: list[tuple[str, bool]] = []

        for item in items:
            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                organization=item.organization,
                publication_date=item.date_published.date() if item.date_published else None,
                closing_date=item.closing_date.date() if item.closing_date else None,
                source_record_id=item.source_record_id,
                notice_type=item.bid_status,
                category=item.category,
                status="discovered",
            )

            if not created:
                _update_ontario_tenders_feed_metadata(db, opportunity, item)

            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db, run, status="success", action="ingest_feed", requested_value=limit,
            requested_unit="items", items_found=len(items), items_inserted=created_count, items_updated=existing_count
        )
        logger.info(
            "Ontario Tenders ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(db, run, status="error", action="ingest_feed", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise


def fetch_ontario_tenders_details(db: Session, limit: int = 10) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "ontario_tenders")
    if source is None:
        raise ValueError("Source 'ontario_tenders' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = OntarioTendersConnector()
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error"),
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)
                parsed = parse_ontario_tenders_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("ontario_tenders", record_id)
                text_path = build_raw_text_path("ontario_tenders", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    title=opp.title or parsed.get("title"),
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=opp.organization or parsed.get("organization"),
                    location=parsed.get("location") or opp.location,
                    publication_date=opp.publication_date or parsed.get("publication_date"),
                    closing_date=opp.closing_date or parsed.get("closing_date"),
                    source_record_id=opp.source_record_id or parsed.get("project_reference"),
                    notice_type=opp.notice_type or parsed.get("notice_type"),
                    category=opp.category or parsed.get("category"),
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )
                results.append((opp.id, "updated"))

            except Exception as exc:
                logger.warning(
                    "Failed to fetch/process Ontario Tenders detail for opportunity %s: %s",
                    opp.id,
                    exc,
                )
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db, run, status="success", action="fetch_details", requested_value=limit,
            requested_unit="items", items_found=len(opportunities), items_updated=updated,
            items_failed=errors, extra={"errors": errors}
        )
        logger.info("Ontario Tenders detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(db, run, status="error", action="fetch_details", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise

def ingest_nationtalk_feed(db: Session, limit: int = 50) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "nationtalk")
    if source is None:
        raise ValueError("Source 'nationtalk' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = NationTalkConnector()
        items = connector.fetch_feed_items(limit=limit)

        results: list[tuple[str, bool]] = []

        for item in items:
            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                publication_date=item.date_published.date() if item.date_published else None,
                notice_type=item.notice_type,
                category=item.category,
                location=item.location,
                status="discovered",
            )
            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db, run, status="success", action="ingest_feed", requested_value=limit,
            requested_unit="items", items_found=len(items), items_inserted=created_count, items_updated=existing_count
        )
        logger.info(
            "NationTalk ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(db, run, status="error", action="ingest_feed", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise

def fetch_nationtalk_details(
    db: Session,
    limit: int = 20,
    *,
    retry_error_after_minutes: int = 60,
    retry_blocked_after_minutes: int = 360,
) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "nationtalk")
    if source is None:
        raise ValueError("Source 'nationtalk' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = NationTalkConnector()
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error", "detail_blocked"),
            retry_error_after_minutes=retry_error_after_minutes,
            retry_blocked_after_minutes=retry_blocked_after_minutes,
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)
                parsed = parse_nationtalk_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("nationtalk", record_id)
                text_path = build_raw_text_path("nationtalk", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    title=parsed.get("title") or opp.title,
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=parsed.get("organization") or opp.organization,
                    location=parsed.get("location") or opp.location,
                    publication_date=parsed.get("publication_date") or opp.publication_date,
                    closing_date=parsed.get("closing_date") or opp.closing_date,
                    notice_type=parsed.get("notice_type") or opp.notice_type,
                    category=parsed.get("category") or opp.category,
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )

                results.append((opp.id, "updated"))

            except Exception as exc:
                logger.warning(
                    "Failed to fetch/process NationTalk detail for opportunity %s: %s",
                    opp.id,
                    exc,
                )
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db, run, status="success", action="fetch_details", requested_value=limit,
            requested_unit="items", items_found=len(opportunities), items_updated=updated,
            items_failed=errors, extra={"errors": errors}
        )
        logger.info("NationTalk detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(db, run, status="error", action="fetch_details", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise

def ingest_chiefs_of_ontario_feed(
    db: Session,
    limit: int = 50,
    pages: int = 5,
) -> list[tuple[str, bool]]:
    source = get_source_by_name(db, "chiefs_of_ontario")
    if source is None:
        raise ValueError("Source 'chiefs_of_ontario' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = ChiefsOfOntarioConnector()
        items = connector.fetch_feed_items(limit=limit, pages=pages)

        results: list[tuple[str, bool]] = []

        for item in items:
            opportunity, created = get_or_create_opportunity(
                db,
                source_id=source.id,
                url=str(item.url),
                title=item.title,
                description_raw=item.summary or item.description,
                organization=item.organization,
                publication_date=item.date_published.date() if item.date_published else None,
                status="discovered",
            )
            results.append((opportunity.url, created))

        created_count = sum(1 for _, created in results if created)
        existing_count = len(results) - created_count
        _finish_run(
            db, run, status="success", action="ingest_feed", requested_value=pages,
            requested_unit="pages", items_found=len(items), items_inserted=created_count,
            items_updated=existing_count, extra={"item_limit": limit}
        )
        logger.info(
            "Chiefs of Ontario ingestion completed. total=%s new=%s existing=%s",
            len(results),
            created_count,
            existing_count,
        )
        return results
    except Exception:
        _finish_run(db, run, status="error", action="ingest_feed", requested_value=pages, requested_unit="pages", items_found=0, items_failed=1, extra={"item_limit": limit})
        raise


def fetch_chiefs_of_ontario_details(
    db: Session,
    limit: int = 20,
    *,
    retry_error_after_minutes: int = 60,
    retry_blocked_after_minutes: int = 360,
) -> list[tuple[int, str]]:
    source = get_source_by_name(db, "chiefs_of_ontario")
    if source is None:
        raise ValueError("Source 'chiefs_of_ontario' is not registered in the database.")
    run = _start_run(db, source_id=source.id)

    try:
        connector = ChiefsOfOntarioConnector()
        opportunities = list_opportunities_for_detail_fetch(
            db,
            source_id=source.id,
            limit=limit,
            include_statuses=("discovered", "detail_error", "detail_blocked"),
            retry_error_after_minutes=retry_error_after_minutes,
            retry_blocked_after_minutes=retry_blocked_after_minutes,
        )

        results: list[tuple[int, str]] = []

        for opp in opportunities:
            try:
                html = connector.fetch_notice_html(opp.url)
                parsed = parse_chiefs_of_ontario_notice(html)

                record_id = f"opp_{opp.id}"
                html_path = build_raw_html_path("chiefs_of_ontario", record_id)
                text_path = build_raw_text_path("chiefs_of_ontario", record_id)

                write_text_file(html_path, html)
                write_text_file(text_path, parsed["raw_text"])

                content_hash = sha256_text(html)

                update_opportunity(
                    db,
                    opp,
                    title=parsed.get("title") or opp.title,
                    description_raw=parsed.get("description_raw") or opp.description_raw,
                    organization=parsed.get("organization") or opp.organization,
                    publication_date=parsed.get("publication_date") or opp.publication_date,
                    closing_date=parsed.get("closing_date") or opp.closing_date,
                    notice_type=parsed.get("notice_type") or opp.notice_type,
                    category=parsed.get("category") or opp.category,
                    raw_html_path=str(html_path),
                    raw_text_path=str(text_path),
                    hash_content=content_hash,
                    status="detail_fetched",
                )
                results.append((opp.id, "updated"))

            except Exception as exc:
                logger.warning(
                    "Failed to fetch/process Chiefs of Ontario detail for opportunity %s: %s",
                    opp.id,
                    exc,
                )
                update_opportunity(db, opp, status="detail_error")
                results.append((opp.id, "error"))

        updated = sum(1 for _, status in results if status == "updated")
        errors = sum(1 for _, status in results if status == "error")
        _finish_run(
            db, run, status="success", action="fetch_details", requested_value=limit,
            requested_unit="items", items_found=len(opportunities), items_updated=updated,
            items_failed=errors, extra={"errors": errors}
        )
        logger.info("Chiefs of Ontario detail fetch completed for %s opportunities.", len(results))
        return results
    except Exception:
        _finish_run(db, run, status="error", action="fetch_details", requested_value=limit, requested_unit="items", items_found=0, items_failed=1)
        raise
