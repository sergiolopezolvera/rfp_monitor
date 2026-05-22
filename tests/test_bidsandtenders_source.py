from datetime import datetime

from app.sources.bidsandtenders import BidsAndTendersConnector


def test_fetch_feed_items_extracts_clean_table_metadata() -> None:
    connector = BidsAndTendersConnector()
    connector._request_search_page = lambda **_: {
        "tenders": [
            {
                "id": 12345,
                "name": "RFP-2026-01 - Strategic Planning Services",
                "viewUrl": "/Module/Tenders/en/Tender/Detail/12345",
                "organization": {"displayName": "City of Example"},
                "status": {"displayName": "Open"},
                "convertedPublishDate": "04/19/2026 09:00 AM",
                "convertedClosingDate": "05/01/2026 02:00 PM",
                "bidHasFee": False,
            }
        ],
        "totalCount": 1,
    }

    items = connector.fetch_feed_items(limit=1)

    assert len(items) == 1
    assert items[0].title == "Strategic Planning Services"
    assert items[0].organization == "City of Example"
    assert items[0].source_record_id == "12345"
    assert items[0].date_published == datetime(2026, 4, 19, 9, 0)
    assert items[0].closing_date == datetime(2026, 5, 1, 14, 0)
    assert str(items[0].url) == (
        "https://bids.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/12345"
    )


def test_fetch_feed_items_extracts_current_search_payload() -> None:
    connector = BidsAndTendersConnector()
    connector._request_search_page = lambda **_: {
        "tenders": [
            {
                "Id": "a0265a0c-bddf-498a-8bb7-ebc8dfc2c70b",
                "Title": "001 - REOI: Port of Argentia Demonstration Plant",
                "Status": "Open",
                "Description": "<p>Port of Argentia invites Expressions of Interest.</p>",
                "DateAvailableDisplay": "Wed May 6, 2026 10:00 AM",
                "DateClosingDisplay": "Fri May 22, 2026 11:55 PM (EDT)",
            }
        ],
        "totalCount": 1,
    }

    items = connector.fetch_feed_items(limit=1)

    assert len(items) == 1
    assert items[0].title == "REOI: Port of Argentia Demonstration Plant"
    assert items[0].source_record_id == "a0265a0c-bddf-498a-8bb7-ebc8dfc2c70b"
    assert items[0].date_published == datetime(2026, 5, 6, 10, 0)
    assert items[0].closing_date == datetime(2026, 5, 22, 23, 55)
    assert str(items[0].url) == (
        "https://bids.bidsandtenders.ca/Module/Tenders/en/Tender/Detail/"
        "a0265a0c-bddf-498a-8bb7-ebc8dfc2c70b"
    )
