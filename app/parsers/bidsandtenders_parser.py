from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


TIMEZONE_SUFFIX_RE = re.compile(r"\s+\(([A-Z]{3,5})\)$")
BARE_TIMEZONE_SUFFIX_RE = re.compile(r"\s+([A-Z]{3,5})$")


def html_to_text(html: str) -> str:
    """Convert HTML into simplified plain text."""
    soup = BeautifulSoup(html, "lxml")
    return soup.get_text("\n", strip=True)


def _normalize_whitespace(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = " ".join(value.split())
    return cleaned or None


def _normalize_multiline(value: str | None) -> str | None:
    if not value:
        return None

    lines = [" ".join(line.split()) for line in value.splitlines()]
    cleaned_lines = [line for line in lines if line]
    if not cleaned_lines:
        return None
    return "\n".join(cleaned_lines)


def _text(node: Tag | None, separator: str = " ", multiline: bool = False) -> str | None:
    if node is None:
        return None

    raw = node.get_text(separator, strip=True)
    if multiline:
        return _normalize_multiline(raw)
    return _normalize_whitespace(raw)


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    value = TIMEZONE_SUFFIX_RE.sub("", value)
    value = BARE_TIMEZONE_SUFFIX_RE.sub("", value)

    candidates = [
        "%m/%d/%Y",
        "%Y-%m-%d",
        "%m/%d/%Y %I:%M:%S %p",
        "%m/%d/%Y %I:%M %p",
        "%b %d, %Y %I:%M:%S %p",
        "%b %d, %Y %I:%M %p",
        "%a %b %d, %Y %I:%M:%S %p",
        "%a %b %d, %Y %I:%M %p",
        "%Y-%m-%dT%H:%M:%S",
    ]

    for fmt in candidates:
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    # fallback: try first token chunk before time
    if " " in value:
        head = value.split(" ", 1)[0]
        for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
            try:
                return datetime.strptime(head, fmt).date()
            except ValueError:
                continue

    return None


def _select_text(
    soup: BeautifulSoup | Tag,
    selectors: list[str],
    *,
    separator: str = " ",
    multiline: bool = False,
) -> str | None:
    for selector in selectors:
        node = soup.select_one(selector)
        value = _text(node, separator=separator, multiline=multiline)
        if value:
            return value
    return None


def _extract_first_line_after(text: str, anchor: str) -> str | None:
    if anchor not in text:
        return None

    segment = text.split(anchor, 1)[1].strip()
    for line in segment.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _extract_between(text: str, start: str, end_markers: list[str]) -> str | None:
    if start not in text:
        return None

    segment = text.split(start, 1)[1]
    end_positions = [segment.find(marker) for marker in end_markers if marker in segment]
    end_positions = [pos for pos in end_positions if pos >= 0]

    if end_positions:
        segment = segment[: min(end_positions)]

    return _normalize_multiline(segment.strip())


def _extract_bid_name(text: str) -> str | None:
    return _extract_first_line_after(text, "Bid Name:")


def _extract_bid_status(text: str) -> str | None:
    return _extract_first_line_after(text, "Bid Status:")


def _extract_bid_closing_date(text: str) -> str | None:
    return _extract_first_line_after(text, "Bid Closing Date:")


def _extract_title_from_html(soup: BeautifulSoup) -> str | None:
    selectors = [
        "h1",
        ".tender-title",
        ".page-title",
        "title",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if not node:
            continue

        if node.name == "title":
            value = node.get_text(" ", strip=True)
            value = value.replace(" - Bids and Tenders", "").strip()
        else:
            value = node.get_text(" ", strip=True)

        value = _normalize_whitespace(value)
        if value:
            return value

    return None


def _extract_title_from_text(text: str) -> str | None:
    # common anchors on these pages vary by tenant/theme; this is a fallback
    for anchor in [
        "Bid Information",
        "Bid Name",
        "Tender Name",
    ]:
        value = _extract_first_line_after(text, anchor)
        if value:
            return value
    return None


def _extract_labeled_value(soup: BeautifulSoup, labels: list[str]) -> str | None:
    """
    Generic helper for pages that use label/value layouts.
    Tries common patterns:
    - th/td tables
    - dt/dd definition lists
    - bootstrap rows with label/value classes
    """
    normalized_labels = {label.lower().strip(": ") for label in labels}

    # tables
    for row in soup.select("tr"):
        th = row.select_one("th")
        td = row.select_one("td")
        if th and td:
            label = _text(th)
            if label and label.lower().strip(": ") in normalized_labels:
                return _text(td, separator="\n", multiline=True)

    # definition lists
    for dt in soup.select("dt"):
        label = _text(dt)
        if label and label.lower().strip(": ") in normalized_labels:
            dd = dt.find_next_sibling("dd")
            if isinstance(dd, Tag):
                return _text(dd, separator="\n", multiline=True)

    # generic div-based field rows
    for container in soup.select("div, section, article"):
        children = list(container.children)
        if len(children) < 2:
            continue

    return None


def _build_structured_raw_text(data: dict[str, Any]) -> str:
    lines: list[str] = []

    scalar_fields = [
        ("Title", data.get("title")),
        ("Status", data.get("status")),
        ("Published date", data.get("publication_date").isoformat() if data.get("publication_date") else None),
        ("Closing date", data.get("closing_date").isoformat() if data.get("closing_date") else None),
        ("Organization", data.get("organization")),
        ("Reference number", data.get("reference_number")),
        ("Bid type", data.get("bid_type")),
    ]

    for label, value in scalar_fields:
        if value:
            lines.append(f"{label}: {value}")

    multiline_sections = [
        ("Description", data.get("description_raw")),
    ]

    for label, value in multiline_sections:
        if value:
            lines.append(f"{label}:\n{value}")

    return "\n\n".join(lines)


def parse_bidsandtenders_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    text = html_to_text(html)

    # Prioridad alta: usar Bid Name real antes que títulos genéricos del HTML
    title = (
        _extract_bid_name(text)
        or _extract_title_from_html(soup)
        or _extract_title_from_text(text)
    )

    # organization often appears in breadcrumbs / field rows / metadata
    organization = (
        _extract_labeled_value(soup, ["Organization", "Issuer", "Owner Organization"])
        or _extract_first_line_after(text, "Organization")
    )

    status = (
        _extract_labeled_value(soup, ["Status", "Bid Status"])
        or _extract_bid_status(text)
        or _extract_first_line_after(text, "Status")
    )

    reference_number = (
        _extract_labeled_value(soup, ["Reference Number", "Bid Number", "Tender Number"])
        or _extract_first_line_after(text, "Reference Number")
        or _extract_first_line_after(text, "Bid Number")
        or _extract_first_line_after(text, "Tender Number")
    )

    bid_type = (
        _extract_labeled_value(soup, ["Type", "Bid Type", "Procurement Type"])
        or _extract_first_line_after(text, "Bid Type")
    )

    publication_date_raw = (
        _extract_labeled_value(soup, ["Published Date", "Publish Date", "Issue Date"])
        or _extract_first_line_after(text, "Published Date")
        or _extract_first_line_after(text, "Publish Date")
    )

    closing_date_raw = (
        _extract_labeled_value(soup, ["Closing Date", "Bid Closing Date", "Closing Date & Time"])
        or _extract_bid_closing_date(text)
        or _extract_first_line_after(text, "Closing Date")
        or _extract_first_line_after(text, "Closing Date & Time")
    )

    description = (
        _extract_labeled_value(soup, ["Description", "Project Description", "Bid Description"])
    )

    if not description:
        description = _extract_between(
            text,
            "Description",
            [
                "Bid Documents",
                "Contact Information",
                "Submission Type",
                "Bid Submission Process",
                "Questions",
                "Attachments",
            ],
        )

    data: dict[str, Any] = {
        "title": _normalize_whitespace(title),
        "status": _normalize_whitespace(status),
        "publication_date": _parse_date(publication_date_raw),
        "closing_date": _parse_date(closing_date_raw),
        "description_raw": description,
        "organization": _normalize_whitespace(organization),
        "reference_number": _normalize_whitespace(reference_number),
        "bid_type": _normalize_whitespace(bid_type),
    }

    structured_text = _build_structured_raw_text(data)

    if structured_text and text:
        data["raw_text"] = f"{structured_text}\n\nFULL_TEXT:\n\n{text}"
    elif text:
        data["raw_text"] = text
    else:
        data["raw_text"] = structured_text

    return data
