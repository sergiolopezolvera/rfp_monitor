from __future__ import annotations

from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin

import feedparser
import httpx

from app.logger import logger
from app.schemas import FeedOpportunity

NATIONTALK_BASE_URL = "https://nationtalk.ca"
NATIONTALK_TENDERS_RSS_URL = "https://nationtalk.ca/feed?post_type=vl_tenders"


def _parse_feed_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        logger.warning("Could not parse NationTalk feed datetime value: %r", value)
        return None


class NationTalkConnector:
    source_name = "nationtalk"

    def __init__(self, base_url: str = NATIONTALK_BASE_URL) -> None:
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

    def _normalize_whitespace(self, value: str | None) -> str | None:
        if not value:
            return None

        cleaned = " ".join(value.split())
        return cleaned or None

    def _absolute_url(self, value: str | None) -> str | None:
        value = self._normalize_whitespace(value)
        if not value:
            return None

        return urljoin(self.base_url, value)

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        """
        Fetch NationTalk tender opportunities from the RSS feed.

        This method only discovers opportunities and returns normalized
        FeedOpportunity objects. Detail-page enrichment should happen separately.
        """
        logger.info("Fetching NationTalk tenders RSS: %s", NATIONTALK_TENDERS_RSS_URL)

        parsed_feed = feedparser.parse(NATIONTALK_TENDERS_RSS_URL)

        if getattr(parsed_feed, "bozo", False):
            logger.warning(
                "NationTalk RSS may be malformed: %s",
                getattr(parsed_feed, "bozo_exception", None),
            )

        items: list[FeedOpportunity] = []
        seen_urls: set[str] = set()

        for entry in parsed_feed.entries:
            if len(items) >= limit:
                break

            url = self._absolute_url(entry.get("link"))
            if not url:
                continue

            if url in seen_urls:
                continue

            seen_urls.add(url)

            published_raw = entry.get("published") or entry.get("pubDate")
            updated_raw = entry.get("updated")

            summary = (
                entry.get("summary")
                or entry.get("description")
                or entry.get("content", [{}])[0].get("value")
                if entry.get("content")
                else None
            )

            items.append(
                FeedOpportunity(
                    title=self._normalize_whitespace(entry.get("title")),
                    url=url,
                    summary=summary,
                    description=summary,
                    author=self._normalize_whitespace(entry.get("author")),
                    date_published=_parse_feed_datetime(published_raw),
                    date_updated=_parse_feed_datetime(updated_raw),
                    source_record_id=self._normalize_whitespace(
                        entry.get("id")
                        or entry.get("guid")
                        or entry.get("link")
                        or url
                    ),
                )
            )

        logger.info("Fetched %s NationTalk RSS tender items.", len(items))
        return items

    def fetch_notice_html(self, url: str) -> str:
        """
        Fetch a NationTalk tender detail page.

        Used later by fetch-nationtalk-details.
        """
        logger.info("Fetching NationTalk tender detail HTML: %s", url)

        response = self.client.get(url)
        response.raise_for_status()

        return response.text