from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import ZipFile

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db import Base
from app.models import Opportunity, Source
from app.services.export_service import export_new_opportunities_to_excel


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
