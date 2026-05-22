from __future__ import annotations

from datetime import datetime
import re
from time import monotonic, sleep
from typing import Final
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.logger import logger
from app.schemas import FeedOpportunity


ONTARIO_TENDERS_BASE_URL: Final[str] = "https://ontariotenders.app.jaggaer.com"
ONTARIO_TENDERS_HOME_URL: Final[str] = (
    f"{ONTARIO_TENDERS_BASE_URL}/esop/nac-host/public/web/login.html"
)
ONTARIO_TENDERS_CURRENT_LIST_URL: Final[str] = (
    f"{ONTARIO_TENDERS_BASE_URL}/esop/guest/go/public/opportunity/current"
    "?locale=en_CA"
    "&customLoginPage=/esop/nac-host/public/web/login.html"
    "&customGuest="
)
DETAIL_ONCLICK_RE: Final[re.Pattern[str]] = re.compile(
    r"goToDetail\(['\"](?P<opportunity_id>\d+)['\"]\s*,\s*['\"](?P<group_id>[^'\"]+)['\"]\)"
)


class OntarioTendersConnector:
    """Connector for the Ontario Tenders Portal/JAGGAER public opportunity list."""

    source_name = "ontario_tenders"

    def __init__(
        self,
        base_url: str = ONTARIO_TENDERS_BASE_URL,
        *,
        min_interval_seconds: float = 5.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.min_interval_seconds = min_interval_seconds
        self.client = httpx.Client(
            headers=self._headers(),
            follow_redirects=True,
            timeout=30.0,
        )
        self._last_request_at = 0.0

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;q=0.9,"
                "image/avif,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Fetch-User": "?1",
            "sec-ch-ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"macOS"',
        }

    def _wait(self) -> None:
        elapsed = monotonic() - self._last_request_at
        if elapsed < self.min_interval_seconds:
            sleep(self.min_interval_seconds - elapsed)

    def _get(self, url: str) -> httpx.Response:
        self._wait()
        response = self.client.get(url)
        self._last_request_at = monotonic()
        response.raise_for_status()
        return response

    def _normalize_whitespace(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    def _parse_datetime(self, value: str | None) -> datetime | None:
        value = self._normalize_whitespace(value)
        if not value:
            return None

        candidates = [
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        logger.warning("Could not parse Ontario Tenders datetime value: %r", value)
        return None

    def _extract_detail_ids(self, anchor: Tag) -> tuple[str | None, str | None]:
        onclick = anchor.get("onclick") or ""
        match = DETAIL_ONCLICK_RE.search(onclick)
        if not match:
            return None, None
        return match.group("opportunity_id"), match.group("group_id")

    def _build_detail_url(self, opportunity_id: str) -> str:
        return f"{self.base_url}/esop/toolkit/opportunity/current/{opportunity_id}/detail.si"

    def _extract_feed_items(self, html: str) -> list[FeedOpportunity]:
        soup = BeautifulSoup(html, "lxml")
        items: list[FeedOpportunity] = []
        seen_urls: set[str] = set()

        rows = soup.select("tbody.async-list-tbody tr.table_cnt_body_a, tbody.async-list-tbody tr.table_cnt_body_b")
        if not rows:
            rows = soup.select("tr.table_cnt_body_a, tr.table_cnt_body_b")

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 7:
                continue

            detail_anchor = row.select_one("a.detailLink[onclick]")
            if not isinstance(detail_anchor, Tag):
                continue

            opportunity_id, group_id = self._extract_detail_ids(detail_anchor)
            if not opportunity_id:
                continue

            detail_url = self._build_detail_url(opportunity_id)
            if detail_url in seen_urls:
                continue
            seen_urls.add(detail_url)

            procurement_route = self._normalize_whitespace(cells[0].get_text(" ", strip=True))
            organization = self._normalize_whitespace(cells[1].get_text(" ", strip=True))
            project_reference = self._normalize_whitespace(cells[2].get_text(" ", strip=True))
            title = self._normalize_whitespace(detail_anchor.get_text(" ", strip=True))
            publication_dt = self._parse_datetime(cells[4].get_text(" ", strip=True))
            work_category = self._normalize_whitespace(cells[5].get_text(" ", strip=True))
            closing_dt = self._parse_datetime(cells[6].get_text(" ", strip=True))

            summary_parts = [
                f"Procurement route: {procurement_route}" if procurement_route else None,
                f"Buyer organization: {organization}" if organization else None,
                f"Project reference: {project_reference}" if project_reference else None,
                f"Work category: {work_category}" if work_category else None,
                f"Group ID: {group_id}" if group_id else None,
            ]
            summary = " | ".join(part for part in summary_parts if part)

            items.append(
                FeedOpportunity(
                    title=title,
                    url=detail_url,
                    summary=summary or None,
                    description=None,
                    author=None,
                    date_published=publication_dt,
                    date_updated=None,
                    source_record_id=opportunity_id,
                    organization=organization,
                    closing_date=closing_dt,
                    bid_status=procurement_route,
                    reference_number=project_reference,
                    category=work_category,
                )
            )

        return items
    
    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        logger.info("Fetching Ontario Tenders current opportunities: %s", ONTARIO_TENDERS_CURRENT_LIST_URL)
        response = self._get(ONTARIO_TENDERS_CURRENT_LIST_URL)
        items = self._extract_feed_items(response.text)
        logger.info("Fetched %s Ontario Tenders items.", len(items))
        return items[:limit]

    def _prime_session(self) -> str:
        response = self._get(ONTARIO_TENDERS_CURRENT_LIST_URL)
        return str(response.url)


    def fetch_notice_html(self, url: str) -> str:
        logger.info("Fetching Ontario Tenders notice HTML: %s", url)

        referer_url = self._prime_session()
        absolute_url = urljoin(self.base_url, url)

        self._wait()
        response = self.client.get(
            absolute_url,
            headers={
                "Referer": referer_url,
            },
        )
        self._last_request_at = monotonic()

        logger.info(
            "Ontario Tenders notice response: %s | final_url=%s",
            response.status_code,
            str(response.url),
        )

        response.raise_for_status()
        return response.text
