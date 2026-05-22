from app.parsers.bidsandtenders_parser import parse_bidsandtenders_notice
from app.sources.bidsandtenders import BidsAndTendersConnector


def test_bidsandtenders_feed_datetime_parses_month_name_and_timezone() -> None:
    connector = BidsAndTendersConnector()

    assert connector._parse_datetime("Oct 31, 2035 12:00 PM NDT") == connector._parse_datetime(
        "Oct 31, 2035 12:00 PM"
    )
    assert connector._parse_datetime("Wed Mar 31, 2027 2:00:00 PM (EDT)") == connector._parse_datetime(
        "Wed Mar 31, 2027 2:00:00 PM"
    )


def test_parse_bidsandtenders_notice_extracts_closing_date_from_verbose_label() -> None:
    html = """
    <html>
      <body>
        <h1>Wall Finishes, Ceiling Finishes, Countertops & Supplies</h1>
        <pre>
Bid Status:
Open
Bid Number:
26026-1
Bid Closing Date:
Wed Mar 31, 2027 2:00:00 PM (EDT)
Description:
The DSBN hereby invites submissions from local suppliers.
        </pre>
      </body>
    </html>
    """

    parsed = parse_bidsandtenders_notice(html)

    assert parsed["title"] == "Wall Finishes, Ceiling Finishes, Countertops & Supplies"
    assert parsed["closing_date"].isoformat() == "2027-03-31"
