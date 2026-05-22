from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Opportunity, Source
from app.services.scrape_service import fetch_merx_details


def _build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_fetch_merx_details_backfills_missing_title_and_organization(monkeypatch) -> None:
    db = _build_session()
    source = Source(name="merx", base_url="https://www.merx.com")
    db.add(source)
    db.commit()
    db.refresh(source)

    existing = Opportunity(
        source_id=source.id,
        url="https://www.merx.com/public/supplier/interception/view-notice/443979315295?origin=0",
        title=None,
        organization=None,
        status="discovered",
    )
    db.add(existing)
    db.commit()

    monkeypatch.setattr(
        "app.services.scrape_service.MerxConnector.fetch_notice_html",
        lambda self, url: "<html></html>",
    )
    monkeypatch.setattr(
        "app.services.scrape_service.parse_merx_notice",
        lambda html: {
            "title": "NRFP 7996 - ASL Interpretation Services",
            "organization": "Insurance Corporation of BC",
            "location": "British Columbia",
            "publication_date": date(2026, 4, 21),
            "closing_date": date(2026, 5, 18),
            "solicitation_number": "NRFP 7996",
            "reference_number": "00005007872",
            "notice_type": "NRFP - Negotiated Request for Proposal (Formal)",
            "purchase_type": "Not Stated",
            "description_raw": "ICBC is looking for a qualified service provider.",
            "raw_text": "Title: NRFP 7996 - ASL Interpretation Services",
        },
    )

    results = fetch_merx_details(db, limit=1)
    refreshed = db.get(Opportunity, existing.id)

    assert results == [(existing.id, "updated")]
    assert refreshed is not None
    assert refreshed.title == "NRFP 7996 - ASL Interpretation Services"
    assert refreshed.organization == "Insurance Corporation of BC"
    assert refreshed.closing_date == date(2026, 5, 18)
