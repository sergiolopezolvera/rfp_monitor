from datetime import datetime

from app.sources.ontariotenders import OntarioTendersConnector


def test_extract_feed_items_captures_work_category_as_category() -> None:
    html = """
    <html>
      <body>
        <table>
          <tbody class="async-list-tbody">
            <tr class="table_cnt_body_a">
              <td>Open</td>
              <td>Government of Ontario</td>
              <td>PR-2026-001</td>
              <td>
                <a class="detailLink" onclick="javascript:goToDetail('120042', '01000');stopEventPropagation(event);">
                  Supply and Deliver Test Equipment
                </a>
              </td>
              <td>27/03/2026 11:59</td>
              <td>Other</td>
              <td>24/04/2026 11:00</td>
            </tr>
          </tbody>
        </table>
      </body>
    </html>
    """

    connector = OntarioTendersConnector()
    items = connector._extract_feed_items(html)

    assert len(items) == 1
    assert items[0].title == "Supply and Deliver Test Equipment"
    assert items[0].organization == "Government of Ontario"
    assert items[0].reference_number == "PR-2026-001"
    assert items[0].category == "Other"
    assert items[0].date_published == datetime(2026, 3, 27, 11, 59)
    assert items[0].closing_date == datetime(2026, 4, 24, 11, 0)
