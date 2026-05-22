from __future__ import annotations

from datetime import date
from typing import Any

from bs4 import BeautifulSoup, Tag


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


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    value = value.splitlines()[0].strip()
    value = value[:10].replace("/", "-")

    try:
        return date.fromisoformat(value)
    except ValueError:
        pass

    parts = value.split("-")
    if len(parts) == 3:
        try:
            a, b, c = [int(x) for x in parts]
            if c > 1900:
                try:
                    return date(c, a, b)
                except ValueError:
                    return date(c, b, a)
        except ValueError:
            return None

    return None


def _text(node: Tag | None, separator: str = " ", multiline: bool = False) -> str | None:
    if node is None:
        return None

    raw = node.get_text(separator, strip=True)
    if multiline:
        return _normalize_multiline(raw)
    return _normalize_whitespace(raw)


def _extract_first_line_after(text: str, anchor: str) -> str | None:
    if anchor not in text:
        return None

    segment = text.split(anchor, 1)[1].strip()
    for line in segment.splitlines():
        line = line.strip()
        if line:
            return line
    return None


def _extract_between(text: str, start: str, end: str) -> str | None:
    if start not in text:
        return None

    segment = text.split(start, 1)[1]
    if end in segment:
        segment = segment.split(end, 1)[0]

    return _normalize_whitespace(segment)


def _extract_title_from_html(soup: BeautifulSoup) -> str | None:
    selectors = [
        "h1.solicitationName",
        "main h1",
        "article h1",
        ".page-title",
        "title",
        "h1",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            title = _normalize_whitespace(node.get_text(" ", strip=True))
            if title and title != "MERX : Welcome!" and len(title) <= 500:
                title = title.removesuffix("| MERX").strip()
                return title

    return None


def _extract_title_from_text(text: str) -> str | None:
    return _normalize_whitespace(_extract_first_line_after(text, "Title"))


def _extract_merx_field_map(soup: BeautifulSoup) -> dict[str, str]:
    fields: dict[str, str] = {}

    for field in soup.select(".previewTab .mets-field"):
        label = _text(field.select_one(".mets-field-label"), separator=" ")
        body = _text(field.select_one(".mets-field-body"), separator="\n", multiline=True)
        if label and body:
            fields[label] = body

    return fields


def _build_structured_raw_text(data: dict[str, Any]) -> str:
    lines: list[str] = []

    scalar_fields = [
        ("Title", data.get("title")),
        ("Status", data.get("status")),
        ("Reference Number", data.get("reference_number")),
        ("Solicitation Number", data.get("solicitation_number")),
        ("Issuing Organization", data.get("organization")),
        ("Solicitation Type", data.get("notice_type")),
        ("Location", data.get("location")),
        ("Purchase Type", data.get("purchase_type")),
        ("Publication date", data.get("publication_date").isoformat() if data.get("publication_date") else None),
        ("Closing date", data.get("closing_date").isoformat() if data.get("closing_date") else None),
        ("Contact name", data.get("contact_name")),
        ("Contact email", data.get("contact_email")),
        ("Contact phone", data.get("contact_phone")),
    ]

    for label, value in scalar_fields:
        if value:
            lines.append(f"{label}: {value}")

    multiline_sections = [
        ("AI Overview", data.get("ai_overview")),
        ("Description", data.get("description_raw")),
        ("Disclaimer", data.get("disclaimer")),
    ]

    for label, value in multiline_sections:
        if value:
            lines.append(f"{label}:\n{value}")

    return "\n\n".join(lines)


def parse_merx_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    text = html_to_text(html)
    fields = _extract_merx_field_map(soup)

    title = _extract_title_from_html(soup) or _extract_title_from_text(text)
    organization = fields.get("Issuing Organization") or _extract_first_line_after(text, "Issuing Organization")
    location = fields.get("Location") or _extract_first_line_after(text, "Location")

    publication_date_raw = fields.get("Publication")
    if not publication_date_raw and "DATES\nPublication" in text:
        publication_date_raw = _extract_first_line_after(text, "DATES\nPublication")
    if not publication_date_raw:
        publication_date_raw = _extract_first_line_after(text, "Publication")

    closing_date_raw = fields.get("Closing Date") or _extract_first_line_after(text, "Closing Date")

    description = _text(soup.select_one(".description .mets-field-body"), separator="\n", multiline=True)
    if not description:
        description = _extract_between(text, "Description", "See more [javascript:void(0);]")
    if not description:
        description = _extract_between(text, "Description", "Categories")
    if not description:
        description = _extract_between(text, "Description", "Documents")
    if not description:
        description = _extract_between(text, "Description", "Contact Information")
    if not description:
        description = _extract_between(text, "Description", "Closing Date")

    data: dict[str, Any] = {
        "title": _normalize_whitespace(title),
        "publication_date": _parse_date(publication_date_raw),
        "closing_date": _parse_date(closing_date_raw),
        "description_raw": description,
        "organization": _normalize_whitespace(organization),
        "location": _normalize_whitespace(location),
        "reference_number": fields.get("Reference Number"),
        "solicitation_number": fields.get("Solicitation Number"),
        "notice_type": fields.get("Solicitation Type"),
        "purchase_type": fields.get("Purchase Type"),
        "status": _text(soup.select_one(".solicitationStatusTimerText")),
        "contact_name": fields.get("Contact Information"),
        "contact_email": None,
        "contact_phone": None,
        "ai_overview": _text(soup.select_one("#ai-private-overview-content"), separator="\n", multiline=True),
        "disclaimer": _text(soup.select_one(".buyerHeader .disclaimer"), separator="\n", multiline=True),
    }

    contact_lines = []
    for node in soup.select(".content-block-sub-title + .twoColFields .mets-field.no-label .mets-field-body"):
        value = _text(node, separator="\n", multiline=True)
        if value:
            contact_lines.append(value)

    if contact_lines:
        data["contact_name"] = contact_lines[0]
    if len(contact_lines) > 1:
        data["contact_email"] = contact_lines[1]
    if len(contact_lines) > 2:
        data["contact_phone"] = contact_lines[2]

    data["raw_text"] = _build_structured_raw_text(data)
    return data
