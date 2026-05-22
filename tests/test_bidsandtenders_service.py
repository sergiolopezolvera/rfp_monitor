from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Opportunity, Source
from app.schemas import FeedOpportunity
from app.services.scrape_service import ingest_bidsandtenders_feed


def _build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_ingest_bidsandtenders_feed_refreshes_existing_rows_from_feed(monkeypatch) -> None:
    db = _build_session()
    source = Source(name="bidsandtenders", base_url="https://bidsandtenders.ic9.esolg.ca")
    db.add(source)
    db.commit()
    db.refresh(source)

    existing = Opportunity(
        source_id=source.id,
        url="https://bidsandtenders.ic9.esolg.ca/Module/Tenders/en/Tender/Detail/12345",
        title="Old noisy detail title",
        organization=None,
        publication_date=None,
        closing_date=date(2026, 4, 30),
        source_record_id=None,
        description_raw=None,
        status="discovered",
    )
    db.add(existing)
    db.commit()

    feed_item = FeedOpportunity(
        title="Strategic Planning Services",
        url="https://bidsandtenders.ic9.esolg.ca/Module/Tenders/en/Tender/Detail/12345",
        summary="Organization: City of Example | Bid status: Open | Reference number: RFP-2026-01",
        description=None,
        date_published=datetime(2026, 4, 19, 9, 0),
        closing_date=datetime(2026, 5, 1, 14, 0),
        source_record_id="12345",
        organization="City of Example",
        bid_status="Open",
        reference_number="RFP-2026-01",
    )

    monkeypatch.setattr(
        "app.services.scrape_service.BidsAndTendersConnector.fetch_feed_items",
        lambda self, limit=50: [feed_item],
    )

    results = ingest_bidsandtenders_feed(db, limit=1)
    refreshed = db.get(Opportunity, existing.id)

    assert results == [(existing.url, False)]
    assert refreshed is not None
    assert refreshed.title == "Strategic Planning Services"
    assert refreshed.organization == "City of Example"
    assert refreshed.publication_date == date(2026, 4, 19)
    assert refreshed.closing_date == date(2026, 5, 1)
    assert refreshed.source_record_id == "12345"
    assert refreshed.description_raw == feed_item.summary
