from datetime import datetime
from email.utils import parsedate_to_datetime
from importlib.util import find_spec
from time import monotonic, sleep
from typing import Final

import feedparser
import httpx

from app.logger import logger
from app.schemas import FeedOpportunity

CANADABUYS_RSS_URL = (
    "https://canadabuys.canada.ca/en/search-feed?"
    "q=a%3a9%3a%7bs%3a13%3a%22search_filter%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a0%3a%22%22%3B%7d"
    "s%3a8%3a%22category%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a3%3a%22154%22%3B%7d"
    "s%3a11%3a%22notice_type%22%3Ba%3a4%3a%7bi%3a0%3Bs%3a4%3a%221681%22%3B"
    "i%3a1%3Bs%3a4%3a%221682%22%3Bi%3a2%3Bs%3a4%3a%221684%22%3B"
    "i%3a3%3Bs%3a4%3a%221685%22%3B%7d"
    "s%3a6%3a%22status%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a2%3a%2287%22%3B%7d"
    "s%3a8%3a%22location%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a4%3a%221218%22%3B%7d"
    "s%3a13%3a%22apply_filters%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a13%3a%22apply%20filters%22%3B%7d"
    "s%3a15%3a%22record_per_page%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a2%3a%2250%22%3B%7d"
    "s%3a11%3a%22current_tab%22%3Ba%3a1%3a%7bi%3a0%3Bs%3a1%3a%22t%22%3B%7d"
    "s%3a5%3a%22words%22%3Bs%3a0%3a%22%22%3B%7d&sid=36968"
)
CANADABUYS_HOME_URL: Final[str] = "https://canadabuys.canada.ca/en"
CANADABUYS_SEARCH_URL: Final[str] = "https://canadabuys.canada.ca/en/tender-opportunities"
DEFAULT_HEADERS: Final[dict[str, str]] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language": "en-CA,en-US;q=0.9,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
}
HTTP2_AVAILABLE: Final[bool] = find_spec("h2") is not None
NOTICE_BLOCKED_STATUSES: Final[set[int]] = {403, 429, 503}


def _parse_feed_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


class CanadaBuysConnector:
    source_name = "canadabuys"

    def __init__(
        self,
        feed_url: str = CANADABUYS_RSS_URL,
        *,
        min_interval_seconds: float = 20.0,
        retry_wait_seconds: float = 45.0,
    ) -> None:
        self.feed_url = feed_url
        self.min_interval_seconds = min_interval_seconds
        self.retry_wait_seconds = retry_wait_seconds
        self.client = httpx.Client(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=30.0,
            http2=HTTP2_AVAILABLE,
        )
        self._session_primed = False
        self._last_notice_request_at = 0.0

    class NoticeAccessBlocked(Exception):
        def __init__(self, *, url: str, status_code: int, body_preview: str, retry_after: str | None = None) -> None:
            self.url = url
            self.status_code = status_code
            self.body_preview = body_preview
            self.retry_after = retry_after
            message = f"CanadaBuys blocked notice access with status {status_code} for {url}"
            if retry_after:
                message += f" (Retry-After: {retry_after})"
            super().__init__(message)

    def _prime_notice_session(self) -> None:
        """Warm up the client session so CanadaBuys can set cookies before detail fetches."""
        if self._session_primed:
            return

        for url in (CANADABUYS_HOME_URL, CANADABUYS_SEARCH_URL):
            try:
                response = self.client.get(url)
                logger.info(
                    "CanadaBuys warmup request: %s -> %s | set-cookie=%s",
                    url,
                    response.status_code,
                    "set-cookie" in response.headers,
                )
            except Exception as exc:
                logger.debug("CanadaBuys warmup request failed for %s: %s", url, exc)

        self._session_primed = True

    def _wait_before_notice_request(self) -> None:
        elapsed = monotonic() - self._last_notice_request_at
        if elapsed < self.min_interval_seconds:
            sleep(self.min_interval_seconds - elapsed)

    def _raise_if_blocked(self, response: httpx.Response, url: str) -> None:
        if response.status_code not in NOTICE_BLOCKED_STATUSES:
            return

        raise self.NoticeAccessBlocked(
            url=url,
            status_code=response.status_code,
            body_preview=response.text[:250].replace("\n", " "),
            retry_after=response.headers.get("retry-after"),
        )

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        logger.info("Fetching CanadaBuys RSS feed...")
        response = self.client.get(
            self.feed_url,
            headers={
                "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
                "Referer": CANADABUYS_SEARCH_URL,
            },
        )

        logger.info("CanadaBuys feed status code: %s", response.status_code)
        logger.info("CanadaBuys feed content-type: %s", response.headers.get("content-type"))
        logger.info("CanadaBuys feed final URL: %s", str(response.url))
        logger.info("CanadaBuys feed response length: %s", len(response.text))

        preview = response.text[:500].replace("\n", " ")
        logger.info("CanadaBuys feed preview: %s", preview)

        parsed = feedparser.parse(response.text)

        logger.info("CanadaBuys parsed entries: %s", len(parsed.entries))
        logger.info("CanadaBuys bozo flag: %s", getattr(parsed, "bozo", None))
        if getattr(parsed, "bozo", 0):
            logger.warning("CanadaBuys bozo_exception: %s", getattr(parsed, "bozo_exception", None))

        items: list[FeedOpportunity] = []

        for entry in parsed.entries[:limit]:
            try:
                item = FeedOpportunity(
                    title=getattr(entry, "title", None),
                    url=getattr(entry, "link", None),
                    summary=getattr(entry, "summary", None),
                    description=getattr(entry, "description", None),
                    author=getattr(entry, "author", None),
                    date_published=_parse_feed_datetime(getattr(entry, "published", None)),
                    date_updated=_parse_feed_datetime(getattr(entry, "updated", None)),
                )
                items.append(item)
            except Exception as exc:
                logger.warning("Failed to parse CanadaBuys feed item: %s", exc)

        logger.info("Fetched %s items from CanadaBuys RSS.", len(items))
        return items
    
    def fetch_notice_html(self, url: str) -> str:
        """Download the HTML for a specific CanadaBuys notice page."""
        logger.info("Fetching CanadaBuys notice HTML: %s", url)
        self._prime_notice_session()
        self._wait_before_notice_request()

        response = self.client.get(
            url,
            headers={
                "Referer": CANADABUYS_SEARCH_URL,
                "Upgrade-Insecure-Requests": "1",
            },
        )
        self._last_notice_request_at = monotonic()

        if response.status_code in NOTICE_BLOCKED_STATUSES:
            logger.warning(
                "CanadaBuys returned %s for %s. Retrying once. retry_after=%s body_preview=%s",
                response.status_code,
                url,
                response.headers.get("retry-after"),
                response.text[:250].replace("\n", " "),
            )
            sleep(self.retry_wait_seconds)
            self.client.get(
                self.feed_url,
                headers={
                    "Accept": "application/rss+xml,application/xml;q=0.9,text/xml;q=0.8,*/*;q=0.7",
                    "Referer": CANADABUYS_SEARCH_URL,
                },
            )
            response = self.client.get(
                url,
                headers={
                    "Referer": CANADABUYS_HOME_URL,
                    "Upgrade-Insecure-Requests": "1",
                },
            )
            self._last_notice_request_at = monotonic()

        logger.info(
            "CanadaBuys notice response: %s | content-type=%s | final_url=%s",
            response.status_code,
            response.headers.get("content-type"),
            str(response.url),
        )
        self._raise_if_blocked(response, url)
        response.raise_for_status()
        return response.text
