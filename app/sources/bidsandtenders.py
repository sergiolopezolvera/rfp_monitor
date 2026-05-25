from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.logger import logger
from app.schemas import FeedOpportunity

BIDS_AND_TENDERS_BASE_URL = "https://bids.bidsandtenders.ca"
TIMEZONE_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{3,5})\)$")
BARE_TIMEZONE_SUFFIX_RE = re.compile(r"\s+([A-Z]{3,5})$")


class BidsAndTendersConnector:
    source_name = "bidsandtenders"

    def __init__(self, base_url: str = BIDS_AND_TENDERS_BASE_URL) -> None:
        self.base_url = base_url.rstrip("/")
        self.home_path = "/Module/Tenders/en"
        self.node_id: str | None = None
        self.request_verification_token: str | None = None
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
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}{self.home_path}",
        }

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """
        Parse date/datetime values returned by the Bids & Tenders search endpoint.

        In practice, this endpoint usually returns normalized values like:
        - 10/31/2035 12:00:00 PM
        - 10/31/2035 12:00 PM
        - 10/31/2035
        - 2025-10-31T12:00:00
        """
        if not value:
            return None

        value = value.strip()
        if not value:
            return None

        # Strip trailing timezone abbreviations like "NDT" or parenthesized ones.
        value = TIMEZONE_SUFFIX_RE.sub("", value)
        value = BARE_TIMEZONE_SUFFIX_RE.sub("", value)

        candidates = [
            "%m/%d/%Y %I:%M:%S %p",
            "%m/%d/%Y %I:%M %p",
            "%m/%d/%Y",
            "%b %d, %Y %I:%M:%S %p",
            "%b %d, %Y %I:%M %p",
            "%a %b %d, %Y %I:%M:%S %p",
            "%a %b %d, %Y %I:%M %p",
            "%a %b %d, %Y %H:%M:%S",
            "%a %b %d, %Y %H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
        ]

        for fmt in candidates:
            try:
                return datetime.strptime(value, fmt)
            except ValueError:
                continue

        logger.warning("Could not parse Bids & Tenders datetime value: %r", value)
        return None

    def _normalize_whitespace(self, value: str | None) -> str | None:
        if value is None:
            return None

        cleaned = " ".join(value.split())
        return cleaned or None

    def _build_absolute_url(self, url: str | None) -> str | None:
        if not url:
            return None

        url = url.strip()
        if not url:
            return None

        if url.startswith("http://") or url.startswith("https://"):
            return url

        if url.startswith("/"):
            return f"{self.base_url}{url}"

        return f"{self.base_url}/{url}"

    def _build_detail_url(self, tender: dict[str, Any]) -> str | None:
        view_url = self._build_absolute_url(tender.get("viewUrl"))
        if view_url:
            return view_url

        tender_id = self._normalize_whitespace(str(tender.get("Id") or ""))
        if not tender_id:
            return None

        return f"{self.base_url}{self.home_path}/Tender/Detail/{tender_id}"

    def _extract_organization_name(self, tender: dict[str, Any]) -> str | None:
        organization = tender.get("organization")
        if not isinstance(organization, dict):
            return None

        return self._normalize_whitespace(
            organization.get("displayName") or organization.get("name")
        )

    def _extract_status_name(self, tender: dict[str, Any]) -> str | None:
        tender_status = tender.get("status") or tender.get("Status")

        if isinstance(tender_status, dict):
            return self._normalize_whitespace(
                tender_status.get("displayName") or tender_status.get("name")
            )

        if isinstance(tender_status, str):
            return self._normalize_whitespace(tender_status)

        return None

    def _split_bid_name(self, value: str | None) -> tuple[str | None, str | None]:
        """
        Split values like:
            'RFSQRF2025138 - Road Repair Service'
        into:
            ('RFSQRF2025138', 'Road Repair Service')

        If no clear prefix exists, return (None, cleaned_value).
        """
        cleaned = self._normalize_whitespace(value)
        if not cleaned:
            return None, None

        if " - " in cleaned:
            left, right = cleaned.split(" - ", 1)
            left = self._normalize_whitespace(left)
            right = self._normalize_whitespace(right)

            if left and right:
                return left, right

        return None, cleaned

    def _extract_source_record_id(self, tender: dict[str, Any], view_url: str) -> str | None:
        """
        Prefer explicit record identifiers from the payload when available.
        Fall back to the last URL segment from the detail URL.
        """
        candidate_keys = [
            "id",
            "Id",
            "tenderId",
            "bidId",
            "solicitationId",
            "tenderGuid",
            "guid",
        ]

        for key in candidate_keys:
            value = tender.get(key)
            if value is None:
                continue

            text = self._normalize_whitespace(str(value))
            if text:
                return text

        detail_token = view_url.rstrip("/").split("/")[-1]
        return self._normalize_whitespace(detail_token)

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

    def _load_search_context(self) -> None:
        if self.node_id and self.request_verification_token:
            return

        url = f"{self.base_url}{self.home_path}"
        logger.info("Fetching Bids & Tenders search context: %s", url)
        response = self.client.get(url)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        home_input = soup.find("input", {"id": "Home"})
        node_input = soup.find("input", {"id": "NodeId"})
        token_container = soup.find(id="bidDetailAntiForgery")
        token_input = (
            token_container.find("input", {"name": "__RequestVerificationToken"})
            if token_container
            else None
        )

        home_path = home_input.get("value") if home_input else None
        node_id = node_input.get("value") if node_input else None
        token = token_input.get("value") if token_input else None

        if not isinstance(home_path, str) or not home_path.startswith("/"):
            raise ValueError("Bids & Tenders search context is missing Home path")
        if not isinstance(node_id, str) or not node_id:
            raise ValueError("Bids & Tenders search context is missing NodeId")
        if not isinstance(token, str) or not token:
            raise ValueError("Bids & Tenders search context is missing anti-forgery token")

        self.home_path = home_path.rstrip("/")
        self.node_id = node_id
        self.request_verification_token = token

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
            "Fetching Bids & Tenders search results: page=%s page_size=%s status_id=%s organization_id=%s",
            page_num,
            page_size,
            status_id,
            organization_id,
        )

        status = "Open" if status_id == 1 else ""
        start = (page_num - 1) * page_size
        direction = "ASC" if sort_column == "UtcClosingDate" else sort_dir
        search_url = f"{self.base_url}{self.home_path}/Tender/Search/{self.node_id}"
        search_params = {
            "status": status,
            "limit": page_size,
            "start": start,
            "dir": direction,
            "from": from_date_utc or "",
            "to": to_date_utc or "",
            "sort": f"DateClosing {direction},Id",
        }
        form_data = {
            "keywords": keywords or "",
            "__RequestVerificationToken": self.request_verification_token,
        }

        response = self.client.post(search_url, params=search_params, data=form_data)
        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Unexpected Bids & Tenders response format: expected dict")

        if payload.get("success") is not True:
            raise ValueError(f"Bids & Tenders search failed: {payload}")

        data = payload.get("data")
        if isinstance(data, list):
            return {
                "tenders": data,
                "totalCount": payload.get("total", len(data)),
            }

        if not isinstance(data, dict):
            raise ValueError("Unexpected Bids & Tenders response format: missing data")

        return data

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        items: list[FeedOpportunity] = []
        seen_urls: set[str] = set()

        page_num = 1
        page_size = 25

        while len(items) < limit:
            data = self._request_search_page(
                page_num=page_num,
                page_size=page_size,
                status_id=1,          # Open
                organization_id=0,    # All
                sort_column="UtcClosingDate",
                sort_dir="DESC",
            )

            tenders = data.get("tenders", [])
            if not isinstance(tenders, list) or not tenders:
                break

            for tender in tenders:
                if not isinstance(tender, dict):
                    continue

                view_url = self._build_detail_url(tender)
                if not view_url or view_url in seen_urls:
                    continue

                seen_urls.add(view_url)

                raw_bid_name = tender.get("name") or tender.get("Title")
                reference_number, clean_title = self._split_bid_name(raw_bid_name)
                organization_name = self._extract_organization_name(tender)
                bid_status = self._extract_status_name(tender)

                published_dt = self._parse_datetime(
                    tender.get("convertedPublishDate") or tender.get("DateAvailableDisplay")
                )
                closing_dt = self._parse_datetime(
                    tender.get("convertedClosingDate") or tender.get("DateClosingDisplay")
                )

                has_fee = tender.get("bidHasFee") is True
                source_record_id = self._extract_source_record_id(tender, view_url)

                summary = self._build_summary(
                    organization_name=organization_name,
                    bid_status=bid_status,
                    reference_number=reference_number,
                    has_fee=has_fee,
                )

                # IMPORTANT:
                # This assumes FeedOpportunity has been extended with:
                # - source_record_id: str | None
                # - organization: str | None
                # - closing_date: datetime | None
                # - bid_status: str | None
                # - reference_number: str | None
                #
                # If your schema still uses only the old fields, update app.schemas first.
                item = FeedOpportunity(
                    title=clean_title,
                    url=view_url,
                    summary=summary,
                    description=tender.get("Description"),
                    author=None,
                    date_published=published_dt,
                    date_updated=None,
                    source_record_id=source_record_id,
                    organization=organization_name,
                    closing_date=closing_dt,
                    bid_status=bid_status,
                    reference_number=reference_number,
                )
                items.append(item)

                if len(items) >= limit:
                    break

            total_count = data.get("totalCount")
            if isinstance(total_count, int) and page_num * page_size >= total_count:
                break

            page_num += 1

        logger.info("Fetched %s Bids & Tenders items.", len(items))
        return items

    def fetch_notice_html(self, url: str) -> str:
        logger.info("Fetching Bids & Tenders notice HTML: %s", url)
        response = self.client.get(url)
        response.raise_for_status()
        return response.text
