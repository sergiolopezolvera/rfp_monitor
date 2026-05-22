from app.sources.merx import MerxConnector


def test_extract_feed_items_captures_titles_from_search_results() -> None:
    html = """
    <html>
      <body>
        <section class="solicitation-result">
          <h3>Consulting Services Corporate Business Development Plan</h3>
          <a href="/public/supplier/interception/view-notice/443974194108?origin=0">View Notice</a>
        </section>
        <section class="solicitation-result">
          <a
            href="/public/supplier/interception/view-notice/443974194132?origin=0"
            title="Umbraco CMS Professional Support"
          >
            Notice
          </a>
        </section>
      </body>
    </html>
    """

    connector = MerxConnector()
    items = connector._extract_feed_items(html)

    assert len(items) == 2
    assert str(items[0].url).endswith("/443974194108?origin=0")
    assert items[0].title == "Consulting Services Corporate Business Development Plan"
    assert str(items[1].url).endswith("/443974194132?origin=0")
    assert items[1].title == "Umbraco CMS Professional Support"


def test_extract_feed_items_trims_search_card_metadata_from_title() -> None:
    html = """
    <html>
      <body>
        <section class="solicitation-result">
          <a href="/public/supplier/interception/view-notice/443973918860?origin=0">
            8566Q - Traffic Load Balancer Refresh (CY00095) City Of Richmond, BC British Columbia, CAN 26 day(s) left Published 2026/04/17 Closing 2026/05/14 443973918860
          </a>
        </section>
      </body>
    </html>
    """

    connector = MerxConnector()
    items = connector._extract_feed_items(html)

    assert len(items) == 1
    assert items[0].title == "8566Q - Traffic Load Balancer Refresh (CY00095) City Of Richmond, BC British Columbia"


def test_extract_feed_items_deduplicates_urls() -> None:
    html = """
    <html>
      <body>
        <a href="/public/supplier/interception/view-notice/443974194108?origin=0">First</a>
        <a href="/public/supplier/interception/view-notice/443974194108?origin=0">Second</a>
      </body>
    </html>
    """

    connector = MerxConnector()
    items = connector._extract_feed_items(html)

    assert len(items) == 1
