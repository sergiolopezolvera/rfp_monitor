"""Connector for the bids&tenders public portal (https://bids.bidsandtenders.ca).

The portal is an ASP.NET MVC app. Listing works in two steps:

1. GET the landing page (``/Module/Tenders/en``) as a normal browser page. It holds
   hidden inputs with the module ``Home`` path, the ``NodeId`` used by the search
   endpoint and an anti-forgery token (the matching cookie is kept by the client).
2. POST to ``{Home}/Tender/Search/{NodeId}`` as an AJAX request with the token.
   It answers JSON: ``{"success": true, "data": [...], "total": N}``.

The landing page must NOT be requested with AJAX headers (``X-Requested-With``,
``Accept: application/json``): ASP.NET treats that as a partial request and the
hidden inputs are missing, which made the old connector fail before searching.
"""

from __future__ import annotations

import re
import time
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from pydantic import ValidationError

from app.logger import logger
from app.schemas import FeedOpportunity

BIDS_AND_TENDERS_BASE_URL = "https://bids.bidsandtenders.ca"
DEFAULT_HOME_PATH = "/Module/Tenders/en"

TIMEZONE_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{2,5})\)$")
BARE_TIMEZONE_SUFFIX_RE = re.compile(r"\s+(?!AM$|PM$)([A-Z]{2,5})$")
DOTNET_DATE_RE = re.compile(r"^/Date\((-?\d+)([+-]\d{4})?\)/$")
GUID_RE = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
NODE_ID_SCRIPT_RES = [
    re.compile(rf"/Tender/Search/({GUID_RE})"),
    re.compile(rf"""NodeId["']?\s*[:=]\s*["']({GUID_RE})["']""", re.IGNORECASE),
]
BLOCK_MARKERS = (
    "just a moment...",
    "cf-chl",
    "challenge-platform",
    "incapsula",
    "_incapsula_resource",
    "captcha",
    "access denied",
    "request unsuccessful",
)
RETRY_STATUSES = {429, 500, 502, 503, 504}

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
JSON_ACCEPT = "application/json, text/javascript, */*; q=0.01"

URL_KEYS = ("viewUrl", "url", "detailUrl", "tenderUrl", "bidUrl", "link", "href")
SITE_KEYS = ("siteUrl", "organizationUrl", "baseUrl", "domain", "tenantUrl", "portalUrl")
TITLE_KEYS = ("name", "title", "bidName", "tenderName")
ORG_KEYS = (
    "organization",
    "organizationName",
    "organizationDisplayName",
    "owner",
    "ownerName",
    "buyer",
    "clientName",
    "agency",
)
STATUS_KEYS = ("status", "statusName", "bidStatus")
PUBLISHED_KEYS = (
    "convertedPublishDate",
    "dateAvailableDisplay",
    "dateAvailable",
    "publishDate",
    "datePublished",
    "utcDateAvailable",
)
CLOSING_KEYS = (
    "convertedClosingDate",
    "dateClosingDisplay",
    "dateClosing",
    "closingDate",
    "utcDateClosing",
)
DESCRIPTION_KEYS = ("description", "summary", "shortDescription")
REFERENCE_KEYS = ("referenceNumber", "bidNumber", "tenderNumber", "number")
RECORD_ID_KEYS = ("id", "tenderId", "bidId", "solicitationId", "tenderGuid", "guid")
TOTAL_KEYS = ("total", "totalCount", "recordsTotal", "count")
ROW_KEYS = ("tenders", "items", "rows", "data", "results")
MAX_DESCRIPTION_CHARS = 4000


class BidsAndTendersError(RuntimeError):
    """The portal answered something the connector cannot use."""


class BidsAndTendersBlockedError(BidsAndTendersError):
    """The portal answered with a bot challenge or an access-denied page."""


def _get_field(record: dict[str, Any], keys: Iterable[str]) -> Any:
    """Return the first non-empty value among ``keys``, matching key names case-insensitively."""
    lowered = {str(key).lower(): value for key, value in record.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def _snippet(text: str, length: int = 300) -> str:
    return " ".join(text[:length].split())


def _looks_blocked(response: httpx.Response) -> bool:
    if response.status_code not in {200, 403, 429, 503}:
        return False
    head = response.text[:5000].lower()
    return any(marker in head for marker in BLOCK_MARKERS)


def _describe_response(response: httpx.Response) -> str:
    content_type = response.headers.get("content-type", "?")
    return (
        f"status={response.status_code} content-type={content_type} "
        f"url={response.url} body={_snippet(response.text)!r}"
    )


class BidsAndTendersConnector:
    source_name = "bidsandtenders"

    def __init__(
        self,
        base_url: str = BIDS_AND_TENDERS_BASE_URL,
        *,
        client: httpx.Client | None = None,
        page_size: int = 25,
        max_pages: int = 40,
        request_delay: float = 0.4,
        max_attempts: int = 3,
        retry_backoff: float = 1.5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.home_path = DEFAULT_HOME_PATH
        self.node_id: str | None = None
        self.request_verification_token: str | None = None
        self.page_size = page_size
        self.max_pages = max_pages
        self.request_delay = request_delay
        self.max_attempts = max_attempts
        self.retry_backoff = retry_backoff
        self._owns_client = client is None
        self.client = client or httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en-CA,en;q=0.9"},
            follow_redirects=True,
            timeout=httpx.Timeout(30.0, connect=15.0),
        )
        self._last_request_at = 0.0
        self._warned_synthetic_urls = False

    # ------------------------------------------------------------------ lifecycle

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __enter__(self) -> BidsAndTendersConnector:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ http

    @property
    def landing_url(self) -> str:
        return f"{self.base_url}{self.home_path}"

    def _html_headers(self) -> dict[str, str]:
        return {"Accept": HTML_ACCEPT}

    def _ajax_headers(self) -> dict[str, str]:
        headers = {
            "Accept": JSON_ACCEPT,
            "X-Requested-With": "XMLHttpRequest",
            "Origin": self.base_url,
            "Referer": self.landing_url,
        }
        if self.request_verification_token:
            headers["RequestVerificationToken"] = self.request_verification_token
        return headers

    def _throttle(self) -> None:
        if self.request_delay <= 0:
            return
        wait = self.request_delay - (time.monotonic() - self._last_request_at)
        if wait > 0:
            time.sleep(wait)

    def _send(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """Send a request, retrying network errors and 429/5xx answers."""
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            self._throttle()
            try:
                response = self.client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                last_error = exc
                logger.warning(
                    "Bids & Tenders %s %s failed (attempt %s/%s): %r",
                    method, url, attempt, self.max_attempts, exc,
                )
            else:
                if response.status_code not in RETRY_STATUSES or attempt == self.max_attempts:
                    return response
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}", request=response.request, response=response
                )
                logger.warning(
                    "Bids & Tenders %s %s answered %s (attempt %s/%s)",
                    method, url, response.status_code, attempt, self.max_attempts,
                )
            finally:
                self._last_request_at = time.monotonic()

            if attempt < self.max_attempts:
                time.sleep(self.retry_backoff * (2 ** (attempt - 1)))

        assert last_error is not None
        raise last_error

    def _check_html_response(self, response: httpx.Response, what: str) -> None:
        if _looks_blocked(response):
            raise BidsAndTendersBlockedError(
                f"Bids & Tenders blocked the {what} request (bot challenge). "
                f"{_describe_response(response)}"
            )
        if response.is_error:
            raise BidsAndTendersError(
                f"Bids & Tenders {what} request failed: {_describe_response(response)}"
            )

    # ------------------------------------------------------------------ parsing helpers

    def _parse_datetime(self, value: Any) -> datetime | None:
        """Parse the date formats seen in the search JSON and on detail pages.

        Examples: ``10/31/2035 12:00 PM``, ``Wed Mar 31, 2027 2:00:00 PM (EDT)``,
        ``Oct 31, 2035 12:00 PM NDT``, ``2025-10-31T12:00:00Z``, ``/Date(1716400000000)/``.
        Timezone suffixes are dropped: the wall-clock time is kept.
        """
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, (int, float)):
            seconds = value / 1000 if value > 10**11 else value
            return datetime.fromtimestamp(seconds, UTC).replace(tzinfo=None)

        text = " ".join(str(value).split())
        if not text:
            return None

        dotnet = DOTNET_DATE_RE.match(text)
        if dotnet:
            return datetime.fromtimestamp(int(dotnet.group(1)) / 1000, UTC).replace(tzinfo=None)

        text = TIMEZONE_SUFFIX_RE.sub("", text)
        text = BARE_TIMEZONE_SUFFIX_RE.sub("", text)

        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            pass

        candidates = [
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y %H:%M:%S",
            "%m/%d/%Y %H:%M",
            "%m/%d/%Y",
            "%b %d, %Y %I:%M:%S %p",
            "%b %d, %Y %I:%M %p",
            "%b %d, %Y",
            "%a %b %d, %Y %I:%M:%S %p",
            "%a %b %d, %Y %I:%M %p",
            "%a %b %d, %Y %H:%M:%S",
            "%a %b %d, %Y %H:%M",
            "%a %b %d, %Y",
            "%B %d, %Y %I:%M %p",
            "%B %d, %Y",
        ]
        for fmt in candidates:
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue

        logger.warning("Could not parse Bids & Tenders datetime value: %r", value)
        return None

    def _normalize_whitespace(self, value: Any) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(str(value).split())
        return cleaned or None

    def _html_to_text(self, value: Any) -> str | None:
        if not value:
            return None
        text = str(value)
        if "<" in text and ">" in text:
            text = BeautifulSoup(text, "html.parser").get_text("\n", strip=True)
        lines = [" ".join(line.split()) for line in text.splitlines()]
        cleaned = "\n".join(line for line in lines if line)
        if len(cleaned) > MAX_DESCRIPTION_CHARS:
            cleaned = cleaned[:MAX_DESCRIPTION_CHARS].rstrip() + "…"
        return cleaned or None

    def _build_absolute_url(self, url: Any, base: str | None = None) -> str | None:
        text = self._normalize_whitespace(url)
        if not text:
            return None
        if text.startswith(("http://", "https://")):
            return text
        if text.startswith("//"):
            return f"https:{text}"
        return urljoin(f"{(base or self.base_url).rstrip('/')}/", text.lstrip("/"))

    def _build_detail_url(self, tender: dict[str, Any]) -> str | None:
        explicit = _get_field(tender, URL_KEYS)
        if explicit:
            site = self._normalize_whitespace(_get_field(tender, SITE_KEYS))
            if site and not site.startswith(("http://", "https://")):
                site = f"https://{site}"
            return self._build_absolute_url(explicit, base=site)

        tender_id = self._normalize_whitespace(_get_field(tender, ("id",)))
        if not tender_id:
            return None

        site = self._normalize_whitespace(_get_field(tender, SITE_KEYS))
        if site:
            if not site.startswith(("http://", "https://")):
                site = f"https://{site}"
            return f"{site.rstrip('/')}{DEFAULT_HOME_PATH}/Tender/Detail/{tender_id}"

        if not self._warned_synthetic_urls:
            self._warned_synthetic_urls = True
            logger.warning(
                "Bids & Tenders search rows carry no detail URL; building %s/Tender/Detail/<Id>. "
                "Row keys: %s",
                self.landing_url,
                sorted(tender.keys()),
            )
        return f"{self.base_url}{self.home_path}/Tender/Detail/{tender_id}"

    def _extract_organization_name(self, tender: dict[str, Any]) -> str | None:
        organization = _get_field(tender, ORG_KEYS)
        if isinstance(organization, dict):
            return self._normalize_whitespace(
                _get_field(organization, ("displayName", "name", "title"))
            )
        if isinstance(organization, str):
            return self._normalize_whitespace(organization)
        return None

    def _extract_status_name(self, tender: dict[str, Any]) -> str | None:
        tender_status = _get_field(tender, STATUS_KEYS)
        if isinstance(tender_status, dict):
            return self._normalize_whitespace(
                _get_field(tender_status, ("displayName", "name"))
            )
        if isinstance(tender_status, str):
            return self._normalize_whitespace(tender_status)
        return None

    def _split_bid_name(self, value: Any) -> tuple[str | None, str | None]:
        """Split ``'RFSQRF2025138 - Road Repair Service'`` into reference and title."""
        cleaned = self._normalize_whitespace(value)
        if not cleaned:
            return None, None

        if " - " in cleaned:
            left, right = cleaned.split(" - ", 1)
            left = self._normalize_whitespace(left)
            right = self._normalize_whitespace(right)
            # A reference is a short code, not the first half of a sentence.
            if left and right and len(left) <= 40 and len(left.split()) <= 4:
                return left, right

        return None, cleaned

    def _extract_source_record_id(self, tender: dict[str, Any], view_url: str) -> str | None:
        value = self._normalize_whitespace(_get_field(tender, RECORD_ID_KEYS))
        if value:
            return value
        return self._normalize_whitespace(view_url.rstrip("/").split("/")[-1])

    def _build_summary(
        self,
        *,
        organization_name: str | None,
        bid_status: str | None,
        reference_number: str | None,
        has_fee: bool,
    ) -> str | None:
        parts: list[str] = []
        if organization_name:
            parts.append(f"Organization: {organization_name}")
        if bid_status:
            parts.append(f"Bid status: {bid_status}")
        if reference_number:
            parts.append(f"Reference number: {reference_number}")
        if has_fee:
            parts.append("This bid contains additional document fees.")
        return " | ".join(parts) if parts else None

    # ------------------------------------------------------------------ search context

    def _load_search_context(self, *, force: bool = False) -> None:
        if not force and self.node_id:
            return

        url = self.landing_url
        logger.info("Fetching Bids & Tenders search context: %s", url)
        response = self._send("GET", url, headers=self._html_headers())
        self._check_html_response(response, "landing page")

        # Follow a redirect to another host (e.g. a renamed portal).
        final = urlsplit(str(response.url))
        if final.scheme and final.netloc:
            self.base_url = f"{final.scheme}://{final.netloc}"

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        def _input_value(name: str) -> str | None:
            node = soup.find("input", {"id": name}) or soup.find("input", {"name": name})
            value = node.get("value") if node else None
            return value.strip() if isinstance(value, str) and value.strip() else None

        home_path = _input_value("Home")
        if home_path and home_path.startswith("/"):
            self.home_path = home_path.rstrip("/")
        elif "/Module/Tenders" in final.path:
            self.home_path = final.path.rstrip("/")

        node_id = _input_value("NodeId")
        if not node_id:
            for pattern in NODE_ID_SCRIPT_RES:
                match = pattern.search(html)
                if match:
                    node_id = match.group(1)
                    break
        if not node_id:
            title = soup.title.get_text(" ", strip=True) if soup.title else None
            raise BidsAndTendersError(
                "Bids & Tenders landing page has no NodeId, so the search endpoint is unknown. "
                f"The page layout may have changed. title={title!r} {_describe_response(response)}"
            )

        token = None
        container = soup.find(id="bidDetailAntiForgery")
        for scope in (container, soup):
            if scope is None:
                continue
            token_input = scope.find("input", {"name": "__RequestVerificationToken"})
            value = token_input.get("value") if token_input else None
            if isinstance(value, str) and value.strip():
                token = value.strip()
                break
        if not token:
            logger.warning(
                "Bids & Tenders landing page has no anti-forgery token; searching without it."
            )

        self.node_id = node_id
        self.request_verification_token = token
        logger.info(
            "Bids & Tenders search context ready: home=%s node=%s token=%s",
            self.home_path,
            node_id,
            "yes" if token else "no",
        )

    # ------------------------------------------------------------------ search

    def _decode_search_payload(self, response: httpx.Response) -> Any:
        if _looks_blocked(response):
            raise BidsAndTendersBlockedError(
                f"Bids & Tenders blocked the search request. {_describe_response(response)}"
            )
        if response.is_error:
            raise BidsAndTendersError(
                f"Bids & Tenders search request failed: {_describe_response(response)}"
            )
        try:
            return response.json()
        except ValueError as exc:
            raise BidsAndTendersError(
                f"Bids & Tenders search did not return JSON: {_describe_response(response)}"
            ) from exc

    def _normalize_search_payload(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, list):
            return {"tenders": payload, "totalCount": len(payload)}

        if not isinstance(payload, dict):
            raise BidsAndTendersError(
                f"Unexpected Bids & Tenders search payload type: {type(payload).__name__}"
            )

        if payload.get("success") is False:
            message = _get_field(payload, ("message", "msg", "error", "errors"))
            raise BidsAndTendersError(f"Bids & Tenders search failed: {message or payload}")

        total = _get_field(payload, TOTAL_KEYS)
        data = _get_field(payload, ROW_KEYS)

        if isinstance(data, dict):
            rows = _get_field(data, ROW_KEYS)
            total = _get_field(data, TOTAL_KEYS) if total is None else total
            data = rows

        if not isinstance(data, list):
            raise BidsAndTendersError(
                f"Bids & Tenders search payload has no result rows. keys={sorted(payload.keys())}"
            )

        try:
            total_count: int | None = int(total) if total is not None else None
        except (TypeError, ValueError):
            total_count = None

        return {"tenders": data, "totalCount": total_count}

    def _request_search_page(
        self,
        *,
        page_num: int,
        page_size: int = 25,
        keywords: str | None = None,
        status_id: int = 1,
        organization_id: int = 0,
        sort_column: str = "UtcClosingDate",
        sort_dir: str = "DESC",
        from_date_utc: str | None = None,
        to_date_utc: str | None = None,
    ) -> dict[str, Any]:
        self._load_search_context()

        logger.info(
            "Fetching Bids & Tenders search results: page=%s page_size=%s status_id=%s",
            page_num,
            page_size,
            status_id,
        )

        status = "Open" if status_id == 1 else ""
        direction = "ASC" if sort_column == "UtcClosingDate" else sort_dir
        params = {
            "status": status,
            "limit": page_size,
            "start": (page_num - 1) * page_size,
            "dir": direction,
            "from": from_date_utc or "",
            "to": to_date_utc or "",
            "sort": f"DateClosing {direction},Id",
        }

        for attempt in (1, 2):
            form_data = {"keywords": keywords or ""}
            if self.request_verification_token:
                form_data["__RequestVerificationToken"] = self.request_verification_token
            search_url = f"{self.base_url}{self.home_path}/Tender/Search/{self.node_id}"
            response = self._send(
                "POST", search_url, params=params, data=form_data, headers=self._ajax_headers()
            )
            # An expired token/cookie pair answers 400/403 or an HTML error page:
            # reload the landing page once and try again.
            content_type = response.headers.get("content-type", "")
            stale = response.status_code in {400, 403, 419} or "html" in content_type
            if attempt == 1 and stale and not _looks_blocked(response):
                logger.warning(
                    "Bids & Tenders search answered %s (%s); refreshing search context.",
                    response.status_code,
                    content_type or "no content-type",
                )
                self._load_search_context(force=True)
                continue
            break

        return self._normalize_search_payload(self._decode_search_payload(response))

    def _tender_to_item(self, tender: dict[str, Any]) -> FeedOpportunity | None:
        view_url = self._build_detail_url(tender)
        if not view_url:
            return None

        reference_number, clean_title = self._split_bid_name(_get_field(tender, TITLE_KEYS))
        reference_number = reference_number or self._normalize_whitespace(
            _get_field(tender, REFERENCE_KEYS)
        )
        organization_name = self._extract_organization_name(tender)
        bid_status = self._extract_status_name(tender)
        has_fee = _get_field(tender, ("bidHasFee", "hasFee")) is True

        return FeedOpportunity(
            title=clean_title,
            url=view_url,
            summary=self._build_summary(
                organization_name=organization_name,
                bid_status=bid_status,
                reference_number=reference_number,
                has_fee=has_fee,
            ),
            description=self._html_to_text(_get_field(tender, DESCRIPTION_KEYS)),
            date_published=self._parse_datetime(_get_field(tender, PUBLISHED_KEYS)),
            closing_date=self._parse_datetime(_get_field(tender, CLOSING_KEYS)),
            source_record_id=self._extract_source_record_id(tender, view_url),
            organization=organization_name,
            bid_status=bid_status,
            reference_number=reference_number,
        )

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        items: list[FeedOpportunity] = []
        seen_urls: set[str] = set()
        page_size = self.page_size

        for page_num in range(1, self.max_pages + 1):
            data = self._request_search_page(
                page_num=page_num,
                page_size=page_size,
                status_id=1,
                sort_column="UtcClosingDate",
            )
            tenders = data.get("tenders") or []
            if not isinstance(tenders, list) or not tenders:
                break

            new_on_page = 0
            for tender in tenders:
                if not isinstance(tender, dict):
                    continue
                try:
                    item = self._tender_to_item(tender)
                except (ValidationError, ValueError) as exc:
                    logger.warning("Skipping malformed Bids & Tenders row %r: %s", tender, exc)
                    continue
                if item is None or str(item.url) in seen_urls:
                    continue

                seen_urls.add(str(item.url))
                items.append(item)
                new_on_page += 1
                if len(items) >= limit:
                    break

            if len(items) >= limit:
                break
            if new_on_page == 0:
                # Same rows as before: the server ignored the paging parameters.
                logger.warning("Bids & Tenders page %s added no new rows; stopping.", page_num)
                break
            if len(tenders) < page_size:
                break
            total_count = data.get("totalCount")
            if isinstance(total_count, int) and page_num * page_size >= total_count:
                break
        else:
            logger.warning("Bids & Tenders paging stopped at max_pages=%s.", self.max_pages)

        logger.info("Fetched %s Bids & Tenders items.", len(items))
        return items

    # ------------------------------------------------------------------ detail pages

    def fetch_notice_html(self, url: str) -> str:
        logger.info("Fetching Bids & Tenders notice HTML: %s", url)
        response = self._send(
            "GET", url, headers={**self._html_headers(), "Referer": self.landing_url}
        )
        self._check_html_response(response, "detail page")
        return response.text
