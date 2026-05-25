from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import LLMAnalysis, Opportunity, Source
from app.services.export_service import (
    export_new_opportunities_to_excel,
    export_opportunities_to_excel,
)


def _build_session() -> Session:
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)()


def test_export_new_opportunities_to_excel_only_includes_last_week(tmp_path: Path) -> None:
    db = _build_session()
    source = Source(name="chiefs_of_ontario", base_url="https://chiefs-of-ontario.org")
    other_source = Source(name="nationtalk", base_url="https://nationtalk.ca")
    db.add_all([source, other_source])
    db.commit()
    db.refresh(source)
    db.refresh(other_source)

    recent = Opportunity(
        source_id=source.id,
        url="https://example.com/recent",
        title="Recent RFP",
        organization="Chiefs of Ontario",
        publication_date=date(2026, 4, 28),
        closing_date=date(2026, 5, 12),
        status="detail_fetched",
        description_raw="Recent opportunity",
        created_at=datetime.utcnow() - timedelta(days=2),
        updated_at=datetime.utcnow() - timedelta(days=1),
    )
    old = Opportunity(
        source_id=source.id,
        url="https://example.com/old",
        title="Old RFP",
        organization="Chiefs of Ontario",
        publication_date=date(2026, 4, 1),
        closing_date=date(2026, 4, 15),
        status="detail_fetched",
        description_raw="Old opportunity",
        created_at=datetime.utcnow() - timedelta(days=10),
        updated_at=datetime.utcnow() - timedelta(days=9),
    )
    recent_other_source = Opportunity(
        source_id=other_source.id,
        url="https://example.com/recent-other",
        title="Recent NationTalk RFP",
        organization="NationTalk",
        publication_date=date(2026, 4, 30),
        closing_date=date(2026, 5, 14),
        status="detail_fetched",
        description_raw="Recent other-source opportunity",
        created_at=datetime.utcnow() - timedelta(days=1),
        updated_at=datetime.utcnow(),
    )

    db.add_all([recent, old, recent_other_source])
    db.commit()
    db.refresh(recent)
    db.refresh(old)
    db.refresh(recent_other_source)

    a1 = LLMAnalysis(opportunity_id=recent.id, is_fit=True, fit_score=2, reasoning="Good fit", matched_services="IT")
    a2 = LLMAnalysis(opportunity_id=old.id, is_fit=True, fit_score=1, reasoning="Okay fit", matched_services="Cloud")
    a3 = LLMAnalysis(opportunity_id=recent_other_source.id, is_fit=True, fit_score=3, reasoning="Great fit", matched_services="Support")
    db.add_all([a1, a2, a3])
    db.commit()


    output_path = tmp_path / "weekly_export.xlsx"
    result = export_new_opportunities_to_excel(db, days=7, output_path=output_path)

    assert result.exported_count == 2
    assert result.output_path == output_path
    assert output_path.exists()

    with ZipFile(output_path) as workbook:
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "Recent RFP" in sheet_xml
    assert "Recent NationTalk RFP" in sheet_xml
    assert "Old RFP" not in sheet_xml
    assert "chiefs_of_ontario" in sheet_xml
    assert "nationtalk" in sheet_xml


def test_export_opportunities_to_excel_filters_by_created_and_closing_dates(tmp_path: Path) -> None:
    db = _build_session()
    source = Source(name="bidsandtenders", base_url="https://bids.bidsandtenders.ca")
    db.add(source)
    db.commit()
    db.refresh(source)

    included = Opportunity(
        source_id=source.id,
        url="https://example.com/included",
        title="Included RFP",
        organization="City of Example",
        publication_date=date(2026, 5, 18),
        closing_date=date(2026, 6, 15),
        status="detail_fetched",
        description_raw="Included opportunity",
        created_at=datetime(2026, 5, 20, 11, 30),
        updated_at=datetime(2026, 5, 20, 12, 0),
    )
    wrong_scrape_date = Opportunity(
        source_id=source.id,
        url="https://example.com/wrong-scrape-date",
        title="Wrong Scrape Date RFP",
        organization="City of Example",
        publication_date=date(2026, 5, 18),
        closing_date=date(2026, 6, 15),
        status="detail_fetched",
        description_raw="Old scrape",
        created_at=datetime(2026, 5, 10, 9, 0),
        updated_at=datetime(2026, 5, 10, 9, 30),
    )
    wrong_closing_date = Opportunity(
        source_id=source.id,
        url="https://example.com/wrong-closing-date",
        title="Wrong Closing Date RFP",
        organization="City of Example",
        publication_date=date(2026, 5, 18),
        closing_date=date(2026, 5, 22),
        status="detail_fetched",
        description_raw="Closing too soon",
        created_at=datetime(2026, 5, 21, 14, 0),
        updated_at=datetime(2026, 5, 21, 14, 30),
    )
    db.add_all([included, wrong_scrape_date, wrong_closing_date])
    db.commit()

    output_path = tmp_path / "filtered_export.xlsx"
    result = export_opportunities_to_excel(
        db,
        created_from=date(2026, 5, 19),
        created_to=date(2026, 5, 22),
        closing_after=date(2026, 6, 1),
        source_name="bidsandtenders",
        output_path=output_path,
    )

    assert result.exported_count == 1
    assert result.output_path == output_path
    assert output_path.exists()

    with ZipFile(output_path) as workbook:
        sheet_xml = workbook.read("xl/worksheets/sheet1.xml").decode("utf-8")

    assert "Included RFP" in sheet_xml
    assert "Wrong Scrape Date RFP" not in sheet_xml
    assert "Wrong Closing Date RFP" not in sheet_xml
    assert "created_at" in sheet_xml
