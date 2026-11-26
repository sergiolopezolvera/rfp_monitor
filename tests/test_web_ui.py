from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import LLMAnalysis, Opportunity, ScrapeRun, Source
from app.web import labels
from app.web.dependencies import get_db
from app.web.main import app


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, future=True)

    with TestingSession() as db:
        source = Source(name="bidsandtenders", base_url="https://bids.bidsandtenders.ca")
        db.add(source)
        db.flush()
        today = date.today()
        open_fit = Opportunity(
            source_id=source.id, url="https://x/1", title="Open good fit",
            closing_date=today + timedelta(days=3), status="detail_fetched",
        )
        closed_fit = Opportunity(
            source_id=source.id, url="https://x/2", title="Closed good fit",
            closing_date=today - timedelta(days=3), status="detail_fetched",
        )
        not_fit = Opportunity(
            source_id=source.id, url="https://x/3", title="Not a fit one",
            closing_date=today + timedelta(days=30), status="detail_fetched",
        )
        pending = Opportunity(source_id=source.id, url="https://x/4", title="Pending one", status="discovered")
        db.add_all([open_fit, closed_fit, not_fit, pending])
        db.flush()
        db.add_all([
            LLMAnalysis(opportunity_id=open_fit.id, model="m", is_fit=True, fit_score=3),
            LLMAnalysis(opportunity_id=closed_fit.id, model="m", is_fit=True, fit_score=2),
            LLMAnalysis(opportunity_id=not_fit.id, model="m", is_fit=False),
        ])
        db.add(ScrapeRun(
            source_id=source.id, status="error", items_found=0, items_failed=1,
            log_summary='{"action": "ingest_feed", "error": "BidsAndTendersError: no NodeId"}',
        ))
        db.commit()

    def _get_db():
        with TestingSession() as db:
            yield db

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_pages_render(client) -> None:
    for path in ("/dashboard", "/sources", "/opportunities", "/opportunities/1"):
        assert client.get(path).status_code == 200


def test_sources_page_shows_plain_labels_and_last_error(client) -> None:
    html = client.get("/sources").text
    assert "Bids &amp; Tenders" in html
    assert "Details pending: 1" in html
    assert "Failed" in html
    assert "no NodeId" in html
    assert "1 waiting" in html  # one posting waiting for "Read details"


def test_single_fit_filter_and_open_only(client) -> None:
    html = client.get("/opportunities?fit=good&open_only=1").text
    assert "Open good fit" in html
    assert "Closed good fit" not in html
    assert "Not a fit one" not in html

    html = client.get("/opportunities?fit=not_fit").text
    assert "Not a fit one" in html
    assert "Open good fit" not in html


def test_old_fit_parameters_still_work(client) -> None:
    html = client.get("/opportunities?fit_result=fit&fit_level=2").text
    assert "Closed good fit" in html
    assert "Open good fit" not in html


def test_open_opportunities_are_listed_first(client) -> None:
    html = client.get("/opportunities").text
    assert html.index("Open good fit") < html.index("Not a fit one") < html.index("Closed good fit")


def test_dashboard_counts(client) -> None:
    html = client.get("/dashboard").text
    assert "Good fits still open" in html
    assert "1 need details" in html


def test_closing_text() -> None:
    today = date.today()
    assert labels.closing_text(today) == "Closes today"
    assert labels.closing_text(today + timedelta(days=1)) == "Tomorrow"
    assert labels.closing_text(today + timedelta(days=9)) == "In 9 days"
    assert labels.closing_text(today - timedelta(days=1)) == "Closed"
    assert labels.closing_text(None) == "No date"


def test_status_and_source_labels() -> None:
    assert labels.status_label("detail_blocked") == "Blocked by site"
    assert labels.source_label("chiefs_of_ontario") == "Chiefs of Ontario"
    assert labels.source_label("some_new_source") == "Some New Source"
