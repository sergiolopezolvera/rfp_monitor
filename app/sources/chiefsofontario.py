from __future__ import annotations

from datetime import datetime
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.logger import logger
from app.schemas import FeedOpportunity

CHIEFS_OF_ONTARIO_BASE_URL = "https://chiefs-of-ontario.org"
UPDATES_PATH = "/about/updates/"
DEFAULT_PAGES = 5


class ChiefsOfOntarioConnector:
    source_name = "chiefs_of_ontario"

    def __init__(self, base_url: str = CHIEFS_OF_ONTARIO_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.client = httpx.Client(
            headers=self._headers(),
            follow_redirects=True,
            timeout=30.0,
        )

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
        }

    def _build_page_url(self, page: int) -> str:
        if page <= 1:
            return f"{self.base_url}{UPDATES_PATH}"
        return f"{self.base_url}{UPDATES_PATH}page/{page}/"

    def _normalize_whitespace(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    def _parse_date(self, value: str | None) -> datetime | None:
        value = self._normalize_whitespace(value)
        if not value:
            return None

        for fmt in ("%B %d, %Y", "%b %d, %Y"):
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        logger.warning("Could not parse Chiefs of Ontario date: %r", value)
        return None

    def _is_relevant_rfp(self, title: str | None, summary: str | None) -> bool:
        text = f"{title or ''} {summary or ''}".lower()
        keywords = [
            "request for proposals",
            "request for proposal",
            "rfp",
            "seeking submissions",
            "seeking proposals",
        ]
        return any(keyword in text for keyword in keywords)

    def _extract_post(self, article: Tag) -> FeedOpportunity | None:
        title_node = article.select_one("h2 a, .entry-title a, a[rel='bookmark']")
        if not title_node:
            return None

        href = title_node.get("href")
        if not href:
            return None

        title = self._normalize_whitespace(title_node.get_text(" ", strip=True))
        url = urljoin(self.base_url, href)

        date_node = article.select_one(
            ".fusion-single-line-meta .updated, "
            ".fusion-post-content-container .updated, "
            ".post-date, "
            "time"
        )

        date_text = None
        if date_node:
            date_text = date_node.get("datetime") or date_node.get_text(" ", strip=True)

        if date_text and "T" in date_text:
            try:
                date_published = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
            except ValueError:
                date_published = self._parse_date(date_text)
        else:
            date_published = self._parse_date(date_text)

        summary_node = article.select_one(
            ".fusion-post-content-container, "
            ".entry-content, "
            ".post-content"
        )
        summary = (
            self._normalize_whitespace(summary_node.get_text(" ", strip=True))
            if summary_node
            else None
        )

        if not self._is_relevant_rfp(title, summary):
            return None

        return FeedOpportunity(
            title=title,
            url=url,
            summary=summary,
            date_published=date_published,
            organization="Chiefs of Ontario",
        )

    def _extract_feed_items(self, html: str) -> list[FeedOpportunity]:
        soup = BeautifulSoup(html, "lxml")
        items: list[FeedOpportunity] = []

        for article in soup.select("article"):
            item = self._extract_post(article)
            if item:
                items.append(item)

        return items

    def fetch_feed_items(self, limit: int = 50, pages: int = DEFAULT_PAGES) -> list[FeedOpportunity]:
        logger.info("Fetching Chiefs of Ontario updates. pages=%s limit=%s", pages, limit)

        items: list[FeedOpportunity] = []
        seen_urls: set[str] = set()

        for page in range(1, pages + 1):
            page_url = self._build_page_url(page)
            logger.info("Fetching Chiefs of Ontario updates page: %s", page_url)

            response = self.client.get(page_url)
            response.raise_for_status()

            page_items = self._extract_feed_items(response.text)

            for item in page_items:
                url = str(item.url)
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                items.append(item)

                if len(items) >= limit:
                    return items

        logger.info("Fetched %s Chiefs of Ontario RFP-like items.", len(items))
        return items

    def fetch_notice_html(self, url: str) -> str:
        logger.info("Fetching Chiefs of Ontario notice HTML: %s", url)
        response = self.client.get(url)
        response.raise_for_status()
        return response.text