from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


DATE_RE = re.compile(r"\b\d{2}/\d{2}/\d{4}(?:\s+\d{2}:\d{2}(?::\d{2})?)?\b")


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
    return "\n".join(cleaned_lines) if cleaned_lines else None

def _dedupe_preserve_order(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []

    for value in values:
        cleaned = _normalize_multiline(value)
        if not cleaned:
            continue

        normalized_key = cleaned.lower()
        if normalized_key in seen:
            continue

        seen.add(normalized_key)
        results.append(cleaned)

    return results


def _text(node: Tag | None, separator: str = " ", multiline: bool = False) -> str | None:
    if node is None:
        return None
    raw = node.get_text(separator, strip=True)
    if multiline:
        return _normalize_multiline(raw)
    return _normalize_whitespace(raw)


def _parse_date(value: str | None) -> date | None:
    value = _normalize_whitespace(value)
    if not value:
        return None

    match = DATE_RE.search(value)
    if match:
        value = match.group(0)

    for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
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


def _extract_title_from_html(soup: BeautifulSoup) -> str | None:
    selectors = [
        "h1 .mainTitle",
        "h1",
        ".mainTitle",
        "title",
    ]
    for selector in selectors:
        node = soup.select_one(selector)
        value = _text(node)
        if not value:
            continue
        value = value.replace("Current Opportunities", "").strip()
        value = value.removesuffix("Ontario Tenders Portal / Portail des appels d'offres de l'Ontario").strip()
        if value and len(value) <= 500:
            return value
    return None


def _extract_labeled_value(soup: BeautifulSoup, labels: list[str]) -> str | None:
    normalized_labels = {label.lower().strip(": ") for label in labels}

    for row in soup.select("tr"):
        cells = row.find_all(["th", "td"], recursive=False)
        if len(cells) >= 2:
            label = _text(cells[0])
            value = _text(cells[1], separator="\n", multiline=True)
            if label and label.lower().strip(": ") in normalized_labels and value:
                return value

    for dt in soup.select("dt"):
        label = _text(dt)
        if label and label.lower().strip(": ") in normalized_labels:
            dd = dt.find_next_sibling("dd")
            if isinstance(dd, Tag):
                return _text(dd, separator="\n", multiline=True)

    text = html_to_text(str(soup))
    for label in labels:
        value = _extract_first_line_after(text, label)
        if value:
            return value
    return None


def _build_structured_raw_text(data: dict[str, Any]) -> str:
    lines: list[str] = []

    scalar_fields = [
        ("Title", data.get("title")),
        ("Status", data.get("status")),
        ("Project reference", data.get("project_reference")),
        ("Buyer organization", data.get("organization")),
        ("Procurement route", data.get("notice_type")),
        ("Work category", data.get("category")),
        ("Publication date", data.get("publication_date").isoformat() if data.get("publication_date") else None),
        ("Closing date", data.get("closing_date").isoformat() if data.get("closing_date") else None),
        ("Contact name", data.get("contact_name")),
        ("Contact email", data.get("contact_email")),
        ("Contact phone", data.get("contact_phone")),
    ]

    for label, value in scalar_fields:
        if value:
            lines.append(f"{label}: {value}")

    if data.get("description_raw"):
        lines.append(f"Description:\n{data['description_raw']}")

    if data.get("raw_text"):
        lines.append(f"FULL_TEXT:\n{data['raw_text']}")

    return "\n\n".join(lines)


def parse_ontario_tenders_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    raw_text = html_to_text(html)

    title = (
        _extract_labeled_value(soup, ["Project Title", "Title", "Opportunity Title"])
        or _extract_title_from_html(soup)
    )
    organization = _extract_labeled_value(soup, ["Buyer Organization", "Purchasing Organization", "Organization"])
    project_reference = _extract_labeled_value(soup, ["Project Reference", "Reference", "Reference Number"])
    notice_type = _extract_labeled_value(soup, ["Procurement Route", "Procurement Type", "Solicitation Type"])
    category = _extract_labeled_value(soup, ["Work Category", "Project Type", "Category"])
    status = _extract_labeled_value(soup, ["Status", "Opportunity Status"])

    publication_date_raw = _extract_labeled_value(soup, ["Publication Date", "First Publishing Date"])
    closing_date_raw = _extract_labeled_value(soup, ["Listing Expiry Date", "Closing Date", "Submission Deadline"])

    contact_name = _extract_labeled_value(soup, ["Contact Name", "Buyer", "Contact"])
    contact_email = _extract_labeled_value(soup, ["Contact Email Address", "Email", "Contact Email"])
    contact_phone = _extract_labeled_value(soup, ["Contact Phone", "Phone", "Telephone"])

    detailed_description = _extract_labeled_value(
        soup,
        ["Detailed Description", "Description", "Project Description", "Abstract"],
    )

    scope_of_work = _extract_labeled_value(
        soup,
        ["Scope of Work", "Scope", "Statement of Work"],
    )

    fallback_description = _extract_between(
        raw_text,
        "Description",
        [
            "Contact",
            "Documents",
            "Categories",
            "Submission",
            "Closing Date",
            "Listing Expiry Date",
        ],
    )

    description_parts = _dedupe_preserve_order([
        detailed_description,
        scope_of_work,
    ])

    description = "\n\n".join(description_parts)
    if not description:
        description = fallback_description

    description = _normalize_multiline(description)

    # limpieza ligera
    if description:
        description = description.replace("\nWork Category", "").strip()

    data: dict[str, Any] = {
        "title": title,
        "description_raw": description,
        "organization": organization,
        "location": None,
        "publication_date": _parse_date(publication_date_raw),
        "closing_date": _parse_date(closing_date_raw),
        "notice_type": notice_type,
        "category": category,
        "status": status,
        "project_reference": project_reference,
        "contact_name": contact_name,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "raw_text": raw_text,
    }
    data["raw_text"] = _build_structured_raw_text(data)
    return data
