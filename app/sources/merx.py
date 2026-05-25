from __future__ import annotations

from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

from app.logger import logger
from app.schemas import FeedOpportunity

MERX_BASE_URL = "https://www.merx.com"
MERX_OPEN_SOLICITATIONS_URL = (
    "https://www.merx.com/public/solicitations/open"
    "?sortDirection=DESC"
    "&pageNumber={page}"
    "&keywords="
    "&pageNumberSelect=1"
    "&publishDate="
    "&sortBy=publicationDate"
    "&solSearchStatus=openSolicitationsTab"
    "&category=10043,10050,10038,10052,10051,10040,10036,10047"
)


class MerxConnector:
    source_name = "merx"

    def __init__(self, base_url: str = MERX_BASE_URL) -> None:
        self.base_url = base_url

    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

    def _build_search_url(self, page: int) -> str:
        return MERX_OPEN_SOLICITATIONS_URL.format(page=page)

    def _normalize_whitespace(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None

    def _closest_result_container(self, anchor: Tag) -> Tag | None:
        container = anchor.find_parent(
            [
                "article",
                "li",
                "tr",
                "section",
            ]
        )
        if container is not None:
            return container

        current = anchor.parent
        while current is not None:
            if not isinstance(current, Tag):
                break

            css_classes = " ".join(current.get("class", []))
            if any(
                token in css_classes.lower()
                for token in ("result", "solicitation", "notice", "listing", "opportunity")
            ):
                return current
            current = current.parent

        return anchor.parent if isinstance(anchor.parent, Tag) else None

    def _extract_item_title(self, anchor: Tag) -> str | None:
        candidates: list[str | None] = [anchor.get("title")]

        container = self._closest_result_container(anchor)
        if container is not None:
            for selector in [
                "a[title]",
                "a[aria-label]",
                "h1",
                "h2",
                "h3",
                "h4",
                ".title a",
                ".title",
                ".solicitationName a",
                ".solicitationName",
                ".solicitationTitle a",
                ".solicitationTitle",
                ".noticeTitle a",
                ".noticeTitle",
                ".opportunityTitle a",
                ".opportunityTitle",
            ]:
                node = container.select_one(selector)
                if node:
                    candidates.append(node.get("title"))
                    candidates.append(node.get("aria-label"))
                    candidates.append(node.get_text(" ", strip=True))

        candidates.append(anchor.get("aria-label"))
        candidates.append(anchor.get_text(" ", strip=True))

        skip_exact = {
            "Notice",
            "Categories",
            "Login",
            "Sign Up",
            "View Notice",
        }

        for candidate in candidates:
            title = self._normalize_whitespace(candidate)
            if not title:
                continue
            if title in skip_exact:
                continue
            if len(title) < 8:
                continue
            if " Published " in title and " Closing " in title:
                title = title.split(" Published ", 1)[0].strip()
            if " day(s) left " in title:
                title = title.split(" day(s) left ", 1)[0].strip()
            if " CAN " in title and any(char.isdigit() for char in title.split(" CAN ", 1)[1]):
                title = title.split(" CAN ", 1)[0].strip()
            title = title.rstrip(",- ")
            if (
                title.endswith(("British Columbia", "Alberta", "Nova Scotia", "Ontario", "Quebec"))
                and " - " not in title
            ):
                continue
            return title

        return None

    def _extract_feed_items(self, html: str) -> list[FeedOpportunity]:
        soup = BeautifulSoup(html, "lxml")
        items: list[FeedOpportunity] = []
        seen: set[str] = set()

        for anchor in soup.find_all("a", href=True):
            href = anchor["href"].strip()

            # Expected pattern from the old Make flow:
            # /public/supplier/solicitations/notice/<id>?origin=0
            if "/public/" not in href:
                continue
            if "?origin=0" not in href:
                continue

            absolute_url = urljoin(self.base_url, href)

            if absolute_url in seen:
                continue

            seen.add(absolute_url)
            items.append(
                FeedOpportunity(
                    url=absolute_url,
                    title=self._extract_item_title(anchor),
                )
            )

        return items

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        logger.info("Fetching MERX open solicitations...")
        items: list[FeedOpportunity] = []
        seen: set[str] = set()
        page = 1

        with httpx.Client(
            headers=self._headers(),
            follow_redirects=True,
            timeout=30.0,
        ) as client:
            while len(items) < limit:
                search_url = self._build_search_url(page)
                logger.info("Fetching MERX search page %s: %s", page, search_url)

                response = client.get(search_url)
                response.raise_for_status()

                page_items = self._extract_feed_items(response.text)
                logger.info("MERX search page %s yielded %s detail URLs", page, len(page_items))

                if not page_items:
                    break

                new_urls_this_page = 0
                for item in page_items:
                    url = str(item.url)
                    if url in seen:
                        continue

                    seen.add(url)
                    new_urls_this_page += 1

                    try:
                        items.append(item)
                    except Exception as exc:
                        logger.warning("Failed to build MERX FeedOpportunity for %s: %s", url, exc)

                    if len(items) >= limit:
                        break

                if new_urls_this_page == 0:
                    break

                page += 1

        logger.info("Fetched %s MERX items.", len(items))
        return items

    def fetch_notice_html(self, url: str) -> str:
        logger.info("Fetching MERX notice HTML: %s", url)

        response = httpx.get(
            url,
            headers=self._headers(),
            follow_redirects=True,
            timeout=30.0,
        )
        response.raise_for_status()
        return response.text
