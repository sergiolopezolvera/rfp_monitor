"""HTTP-level tests for the Bids & Tenders connector, using a fake portal."""

from __future__ import annotations

import json
from datetime import datetime

import httpx
import pytest

from app.sources.bidsandtenders import (
    BidsAndTendersBlockedError,
    BidsAndTendersConnector,
    BidsAndTendersError,
)

NODE_ID = "0f1d2c3b-4a59-4687-9a8b-7c6d5e4f3a21"

LANDING_HTML = f"""
<html><head><title>bids&tenders</title></head><body>
  <input type="hidden" id="Home" value="/Module/Tenders/en" />
  <input type="hidden" id="NodeId" value="{NODE_ID}" />
  <div id="bidDetailAntiForgery">
    <input name="__RequestVerificationToken" type="hidden" value="tok-123" />
  </div>
</body></html>
"""

PARTIAL_HTML = "<div class='grid'>partial view without hidden inputs</div>"


def _row(index: int, **extra) -> dict:
    row = {
        "Id": f"00000000-0000-0000-0000-{index:012d}",
        "Title": f"RFP-{index} - Service {index}",
        "Status": "Open",
        "Description": "<p>Scope of <b>work</b></p>",
        "DateAvailableDisplay": "Wed May 6, 2026 10:00 AM",
        "DateClosingDisplay": "Fri May 22, 2026 11:55 PM (EDT)",
    }
    row.update(extra)
    return row


class FakePortal:
    def __init__(self, rows: list[dict], *, ignore_paging: bool = False) -> None:
        self.rows = rows
        self.ignore_paging = ignore_paging
        self.requests: list[httpx.Request] = []
        self.search_status = 200
        self.fail_first_search_with: int | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path

        if request.method == "GET" and path == "/Module/Tenders/en":
            # Like ASP.NET MVC: AJAX requests get a partial view.
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return httpx.Response(200, html=PARTIAL_HTML)
            return httpx.Response(
                200, html=LANDING_HTML, headers={"set-cookie": "__RequestVerificationToken=c; Path=/"}
            )

        if request.method == "POST" and path == f"/Module/Tenders/en/Tender/Search/{NODE_ID}":
            if self.fail_first_search_with is not None:
                status, self.fail_first_search_with = self.fail_first_search_with, None
                return httpx.Response(status, html="<html>Bad Request</html>")
            form = dict(httpx.QueryParams(request.content.decode()))
            if form.get("__RequestVerificationToken") != "tok-123":
                return httpx.Response(400, html="<html>anti-forgery failed</html>")
            start = 0 if self.ignore_paging else int(request.url.params["start"])
            limit = int(request.url.params["limit"])
            page = self.rows[start : start + limit]
            body = {"success": True, "data": page, "total": len(self.rows)}
            return httpx.Response(self.search_status, json=body)

        if request.method == "GET" and "/Tender/Detail/" in path:
            return httpx.Response(200, html="<html><h1>Detail</h1></html>")

        return httpx.Response(404, html="<html>Not found</html>")


def _connector(portal: FakePortal, **kwargs) -> BidsAndTendersConnector:
    client = httpx.Client(transport=httpx.MockTransport(portal), follow_redirects=True)
    return BidsAndTendersConnector(
        client=client, request_delay=0, retry_backoff=0, **kwargs
    )


def test_landing_page_is_requested_as_html_not_ajax() -> None:
    portal = FakePortal([_row(1)])
    items = _connector(portal).fetch_feed_items(limit=5)

    landing = portal.requests[0]
    assert "X-Requested-With" not in landing.headers
    assert landing.headers["Accept"].startswith("text/html")
    search = portal.requests[1]
    assert search.headers["X-Requested-With"] == "XMLHttpRequest"
    assert search.headers["RequestVerificationToken"] == "tok-123"
    assert len(items) == 1


def test_feed_items_are_mapped_from_current_payload() -> None:
    portal = FakePortal([_row(1)])
    item = _connector(portal).fetch_feed_items(limit=5)[0]

    assert item.title == "Service 1"
    assert item.reference_number == "RFP-1"
    assert item.description == "Scope of\nwork"
    assert item.date_published == datetime(2026, 5, 6, 10, 0)
    assert item.closing_date == datetime(2026, 5, 22, 23, 55)
    assert str(item.url).endswith("/Module/Tenders/en/Tender/Detail/00000000-0000-0000-0000-000000000001")


def test_explicit_tenant_url_and_organization_are_used() -> None:
    row = _row(
        2,
        ViewUrl="https://essex.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/abc",
        OrganizationName="Town of Essex",
    )
    item = _connector(FakePortal([row])).fetch_feed_items(limit=5)[0]

    assert str(item.url) == "https://essex.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/abc"
    assert item.organization == "Town of Essex"


def test_pagination_collects_all_pages_and_stops() -> None:
    portal = FakePortal([_row(i) for i in range(1, 8)])
    items = _connector(portal, page_size=3).fetch_feed_items(limit=50)

    assert len(items) == 7
    searches = [r for r in portal.requests if r.method == "POST"]
    assert [r.url.params["start"] for r in searches] == ["0", "3", "6"]


def test_pagination_stops_when_server_ignores_paging() -> None:
    portal = FakePortal([_row(i) for i in range(1, 8)], ignore_paging=True)
    portal.rows = portal.rows  # total stays 7 but every page returns the first rows
    items = _connector(portal, page_size=3).fetch_feed_items(limit=50)

    assert len(items) == 3
    assert len([r for r in portal.requests if r.method == "POST"]) == 2


def test_stale_token_reloads_context_once() -> None:
    portal = FakePortal([_row(1)])
    portal.fail_first_search_with = 400
    items = _connector(portal).fetch_feed_items(limit=5)

    assert len(items) == 1
    landings = [r for r in portal.requests if r.method == "GET"]
    assert len(landings) == 2


def test_missing_node_id_raises_clear_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, html="<html><title>Maintenance</title></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    with pytest.raises(BidsAndTendersError, match="NodeId.*Maintenance"):
        connector.fetch_feed_items(limit=1)


def test_node_id_is_found_in_scripts_when_inputs_are_gone() -> None:
    html = f"<html><script>var url = '/Module/Tenders/en/Tender/Search/{NODE_ID}';</script></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, html=html)
        return httpx.Response(200, json={"success": True, "data": [_row(1)], "total": 1})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    assert len(connector.fetch_feed_items(limit=1)) == 1
    assert connector.node_id == NODE_ID


def test_html_search_answer_reports_what_came_back() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, html=LANDING_HTML)
        return httpx.Response(200, html="<html>Server Error in '/' Application</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    with pytest.raises(BidsAndTendersError, match="did not return JSON.*Server Error"):
        connector.fetch_feed_items(limit=1)


def test_bot_challenge_is_reported_as_blocked() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, html="<html><title>Just a moment...</title></html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    with pytest.raises(BidsAndTendersBlockedError):
        connector.fetch_feed_items(limit=1)


def test_server_errors_are_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(503, text="busy")
        return httpx.Response(200, html=LANDING_HTML)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    connector._load_search_context()
    assert connector.node_id == NODE_ID
    assert calls["n"] == 2


def test_success_false_payload_surfaces_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, html=LANDING_HTML)
        return httpx.Response(200, content=json.dumps({"success": False, "message": "Invalid sort"}),
                              headers={"content-type": "application/json"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = BidsAndTendersConnector(client=client, request_delay=0, retry_backoff=0)
    with pytest.raises(BidsAndTendersError, match="Invalid sort"):
        connector.fetch_feed_items(limit=1)


def test_detail_page_is_fetched_as_html() -> None:
    portal = FakePortal([_row(1)])
    connector = _connector(portal)
    html = connector.fetch_notice_html(
        "https://bids.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/xyz"
    )
    assert "<h1>Detail</h1>" in html
    assert "X-Requested-With" not in portal.requests[-1].headers


def test_detail_page_404_raises() -> None:
    portal = FakePortal([])
    with pytest.raises(BidsAndTendersError, match="status=404"):
        _connector(portal).fetch_notice_html("https://bids.bidsandtenders.ca/nope")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/Date(1779458100000)/", datetime(2026, 5, 22, 13, 55)),
        ("2026-05-22T23:55:00Z", datetime(2026, 5, 22, 23, 55)),
        ("2026-05-22T23:55:00.123", datetime(2026, 5, 22, 23, 55, 0, 123000)),
        ("Dec 31, 2026 2:00 PM MST", datetime(2026, 12, 31, 14, 0)),
        ("05/01/2026 02:00 PM", datetime(2026, 5, 1, 14, 0)),
        ("", None),
        (None, None),
    ],
)
def test_parse_datetime_formats(value, expected) -> None:
    assert BidsAndTendersConnector(request_delay=0)._parse_datetime(value) == expected
