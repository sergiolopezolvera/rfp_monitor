from __future__ import annotations

from datetime import datetime
import re
from typing import Any

import httpx

from app.logger import logger
from app.schemas import FeedOpportunity


BIDS_AND_TENDERS_BASE_URL = "https://bidsandtenders.ic9.esolg.ca"
BIDS_AND_TENDERS_SEARCH_URL = (
    f"{BIDS_AND_TENDERS_BASE_URL}/Modules/BidsAndTenders/services/bidsSearch.ashx"
)
TIMEZONE_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{3,5})\)$")
BARE_TIMEZONE_SUFFIX_RE = re.compile(r"\s+([A-Z]{3,5})$")


class BidsAndTendersConnector:
    source_name = "bidsandtenders"

    def __init__(self, base_url: str = BIDS_AND_TENDERS_BASE_URL) -> None:
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
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self.base_url}/Modules/BidsAndTenders/index.aspx",
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

    def _extract_organization_name(self, tender: dict[str, Any]) -> str | None:
        organization = tender.get("organization")
        if not isinstance(organization, dict):
            return None

        return self._normalize_whitespace(
            organization.get("displayName") or organization.get("name")
        )

    def _extract_status_name(self, tender: dict[str, Any]) -> str | None:
        tender_status = tender.get("status")

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
        params: dict[str, Any] = {
            "pageNum": page_num,
            "pageSize": page_size,
            "statusId": status_id,
            "organizationId": organization_id,
            "sortColumn": sort_column,
            "sortDir": sort_dir,
        }

        if keywords:
            params["keywords"] = keywords
        if from_date_utc:
            params["fromDateUtc"] = from_date_utc
        if to_date_utc:
            params["toDateUtc"] = to_date_utc

        logger.info(
            "Fetching Bids & Tenders search results: page=%s page_size=%s status_id=%s organization_id=%s",
            page_num,
            page_size,
            status_id,
            organization_id,
        )

        response = self.client.get(BIDS_AND_TENDERS_SEARCH_URL, params=params)
        response.raise_for_status()

        payload = response.json()

        if not isinstance(payload, dict):
            raise ValueError("Unexpected Bids & Tenders response format: expected dict")

        if payload.get("success") is not True:
            raise ValueError(f"Bids & Tenders search failed: {payload}")

        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Unexpected Bids & Tenders response format: missing data object")

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

                view_url = self._build_absolute_url(tender.get("viewUrl"))
                if not view_url or view_url in seen_urls:
                    continue

                seen_urls.add(view_url)

                raw_bid_name = tender.get("name")
                reference_number, clean_title = self._split_bid_name(raw_bid_name)
                organization_name = self._extract_organization_name(tender)
                bid_status = self._extract_status_name(tender)

                published_dt = self._parse_datetime(tender.get("convertedPublishDate"))
                closing_dt = self._parse_datetime(tender.get("convertedClosingDate"))

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
                    description=None,
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
