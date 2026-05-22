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


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None

    value = value.strip()
    try:
        return date.fromisoformat(value[:10].replace("/", "-"))
    except ValueError:
        return None


def _clean_status(value: str | None) -> str | None:
    value = _normalize_whitespace(value)
    if not value:
        return None
    if value.startswith("Status "):
        return value.removeprefix("Status ").strip() or None
    return value


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


def _text(node: Tag | None, separator: str = " ", multiline: bool = False) -> str | None:
    if node is None:
        return None

    raw = node.get_text(separator, strip=True)
    if multiline:
        return _normalize_multiline(raw)
    return _normalize_whitespace(raw)


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


def _select_all_text(
    soup: BeautifulSoup | Tag,
    selector: str,
    *,
    separator: str = " ",
) -> list[str]:
    values: list[str] = []
    for node in soup.select(selector):
        value = _text(node, separator=separator)
        if value and value not in values:
            values.append(value)
    return values


def _extract_summary_fields(soup: BeautifulSoup) -> dict[str, str]:
    summary: dict[str, str] = {}
    summary_root = soup.select_one("#block-eps-wxt-bootstrap-views-block-tender-details-summary dl")
    if summary_root is None:
        return summary

    for field in summary_root.select(":scope > div.views-field"):
        label = _text(field.select_one("dt"), separator=" ")
        value = _text(field.select_one("dd"), separator=" ")
        if label and value:
            summary[label] = value

    return summary


def _extract_documents(soup: BeautifulSoup) -> list[str]:
    documents: list[str] = []
    for row in soup.select(".tender-documents-table tbody tr"):
        title = _text(row.select_one(".field-document_link a"))
        language = _text(row.select_one(".field-language"))
        date_added = _text(row.select_one(".field-date_added"))

        parts = [part for part in [title, language, date_added] if part]
        if parts:
            documents.append(" | ".join(parts))

    return documents


def _extract_related_notices(soup: BeautifulSoup) -> list[str]:
    notices: list[str] = []
    rows = soup.select("#edit-group-related-notices table tbody tr")

    for row in rows:
        title = _text(row.select_one("td.views-field-title"))
        solicitation_number = _text(row.select_one("td.views-field-field-tender-solicitation-number"))
        publication_date = _text(row.select_one("td.views-field-field-tender-publication-date"))
        closing_date = _text(row.select_one("td.views-field-field-tender-closing-date"))

        parts = [part for part in [title, solicitation_number, publication_date, closing_date] if part]
        if parts:
            notices.append(" | ".join(parts))

    return notices


def _extract_title_from_html(soup: BeautifulSoup) -> str | None:
    selectors = [
        "main h1",
        "article h1",
        ".region-content h1",
        "meta[name='dcterms.title']",
        "h1",
    ]

    for selector in selectors:
        node = soup.select_one(selector)
        if node is None:
            continue

        title = node.get("content") if node.name == "meta" else node.get_text(" ", strip=True)
        title = _normalize_whitespace(title)
        if title and title.lower() not in {"buy canadian policy", "tender notice"}:
            return title

    return None


def _extract_title_from_text(text: str) -> str | None:
    working = text

    if "Tender notice" in working and "Solicitation number" in working:
        segment = working.split("Tender notice", 1)[1]
        segment = segment.split("Solicitation number", 1)[0]
        lines = [line.strip() for line in segment.splitlines() if line.strip()]

        skip_exact = {
            "Buy Canadian Policy",
            "Maintenance on CanadaBuys website",
            "SAP Ariba system maintenance",
            "You are here",
            "CanadaBuys Menu",
            "Canada.ca Menu",
        }

        skip_prefixes = (
            "The Government of Canada has introduced new policies",
            "The CanadaBuys website will be down",
            "SAP Ariba will be unavailable",
            "Friday, ",
            "Saturday, ",
            "Sunday, ",
            "Monday, ",
            "Tuesday, ",
            "Wednesday, ",
            "Thursday, ",
        )

        for line in lines:
            if line in skip_exact:
                continue
            if line.startswith(skip_prefixes):
                continue
            if len(line) > 200:
                continue
            return _normalize_whitespace(line)

    if "Solicitation number" in working:
        before = working.split("Solicitation number", 1)[0]
        lines = [line.strip() for line in before.splitlines() if line.strip()]

        skip_exact = {
            "Buy Canadian Policy",
            "Maintenance on CanadaBuys website",
            "SAP Ariba system maintenance",
            "Tender notice",
            "You are here",
            "CanadaBuys Menu",
            "Canada.ca Menu",
        }

        skip_prefixes = (
            "The Government of Canada has introduced new policies",
            "The CanadaBuys website will be down",
            "SAP Ariba will be unavailable",
            "Friday, ",
            "Saturday, ",
            "Sunday, ",
            "Monday, ",
            "Tuesday, ",
            "Wednesday, ",
            "Thursday, ",
        )

        for line in reversed(lines):
            if line in skip_exact:
                continue
            if line.startswith(skip_prefixes):
                continue
            if len(line) > 200:
                continue
            return _normalize_whitespace(line)

    return None


def _build_structured_raw_text(data: dict[str, Any]) -> str:
    lines: list[str] = []

    scalar_fields = [
        ("Title", data.get("title")),
        ("Solicitation number", data.get("solicitation_number")),
        ("Publication date", data.get("publication_date").isoformat() if data.get("publication_date") else None),
        ("Closing date", data.get("closing_date").isoformat() if data.get("closing_date") else None),
        ("Last amendment date", data.get("last_amendment_date").isoformat() if data.get("last_amendment_date") else None),
        ("Status", data.get("status")),
        ("Notice type", data.get("notice_type")),
        ("Language(s)", data.get("languages")),
        ("Region(s) of delivery", data.get("location")),
        ("Contract duration", data.get("contract_duration")),
        ("Procurement method", data.get("procurement_method")),
        ("Selection criteria", data.get("selection_criteria")),
        ("Commodity", data.get("category")),
        ("Organization", data.get("organization")),
        ("Buying organization(s)", data.get("buying_organizations")),
        ("Contracting authority", data.get("contracting_authority")),
        ("Email", data.get("contact_email")),
        ("Phone", data.get("contact_phone")),
    ]

    for label, value in scalar_fields:
        if value:
            lines.append(f"{label}: {value}")

    multiline_sections = [
        ("Description", data.get("description_raw")),
        ("Trade agreements", data.get("trade_agreements")),
        ("Reason for limited tendering", data.get("limited_tendering_reason")),
    ]

    for label, value in multiline_sections:
        if value:
            lines.append(f"{label}:\n{value}")

    list_sections = [
        ("Documents", data.get("documents")),
        ("Related notices", data.get("related_notices")),
    ]

    for label, values in list_sections:
        if values:
            lines.append(label + ":")
            lines.extend(f"- {value}" for value in values)

    return "\n\n".join(lines)


def parse_canadabuys_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    text = html_to_text(html)

    title = _extract_title_from_html(soup) or _extract_title_from_text(text)

    summary = _extract_summary_fields(soup)

    description = _select_text(
        soup,
        ["#edit-group-description .tender-detail-description"],
        separator="\n",
        multiline=True,
    )
    if not description:
        description = _extract_between(text, "Description", "Show more description")
    if not description:
        description = _extract_between(text, "Description", "Contact information")
    if not description:
        description = _extract_between(text, "Description", "Region(s) of delivery")
    if not description:
        description = _extract_between(text, "Description", "Contract duration")

    solicitation_number = _select_text(
        soup,
        [".field--name-field-tender-solicitation-number .field--item"],
    ) or _extract_first_line_after(text, "Solicitation number")

    publication_date_raw = _select_text(
        soup,
        [
            ".field--name-field-tender-publication-date time",
            "meta[name='dcterms.issued']",
            "meta[name='dcterms.created']",
        ],
    ) or _extract_first_line_after(text, "Publication date")

    closing_date_raw = _select_text(
        soup,
        [".closing-date-field .dateclass"],
    ) or _extract_first_line_after(text, "Closing date and time")

    last_amendment_date_raw = _select_text(
        soup,
        [".field--name-field-tender-amendment-date time", "meta[name='dcterms.modified']"],
    )

    organization = _select_text(
        soup,
        [
            "#edit-group-contact-information .field--name-field-tender-contracting-entity .field--name-field-tender-contact-orgname",
            "#edit-group-contact-information .field--name-field-tender-end-user-entities .field--name-field-tender-contact-orgname",
        ],
    )

    location = summary.get("Region(s) of delivery") or _extract_first_line_after(text, "Region(s) of delivery")
    notice_type = summary.get("Notice type")
    languages = summary.get("Language(s)")
    contract_duration = summary.get("Contract duration")
    procurement_method = summary.get("Procurement method")
    selection_criteria = summary.get("Selection criteria")
    category_values = _select_all_text(
        soup,
        "#block-eps-wxt-bootstrap-views-block-tender-details-summary .views-field-field-tender-unspsc li [aria-hidden='true']",
    )
    category = " | ".join(category_values) if category_values else None
    if not category:
        category = summary.get(
            "Commodity - UNSPSC Click the links below to see a list of notices associated with this UNSPSC."
        )
    if not category:
        category = summary.get("Commodity - UNSPSC")

    trade_agreements_list = _select_all_text(
        soup,
        "#edit-group-description .field--name-field-tender-trade-agreements .field--item",
    )
    trade_agreements = "\n".join(trade_agreements_list) if trade_agreements_list else None

    limited_tendering_list = _select_all_text(
        soup,
        "#edit-group-description .field--name-field-tender-ltr .field--item",
    )
    limited_tendering_reason = "\n".join(limited_tendering_list) if limited_tendering_list else None

    buying_organizations_list = _select_all_text(
        soup,
        "#edit-group-contact-information .field--name-field-tender-end-user-entities .field--name-field-tender-contact-orgname",
    )
    buying_organizations = " | ".join(buying_organizations_list) if buying_organizations_list else None

    data: dict[str, Any] = {
        "title": _normalize_whitespace(title),
        "solicitation_number": _normalize_whitespace(solicitation_number),
        "publication_date": _parse_iso_date(publication_date_raw),
        "closing_date": _parse_iso_date(closing_date_raw),
        "last_amendment_date": _parse_iso_date(last_amendment_date_raw),
        "description_raw": description,
        "organization": _normalize_whitespace(organization),
        "location": _normalize_whitespace(location),
        "notice_type": _normalize_whitespace(notice_type),
        "languages": _normalize_whitespace(languages),
        "contract_duration": _normalize_whitespace(contract_duration),
        "procurement_method": _normalize_whitespace(procurement_method),
        "selection_criteria": _normalize_whitespace(selection_criteria),
        "category": _normalize_whitespace(category),
        "status": _clean_status(
            _select_text(soup, ["#tender-status-label"]) or _extract_first_line_after(text, "Status")
        ),
        "contracting_authority": _select_text(
            soup,
            ["#edit-group-contact-information .field--name-field-tender-contact-contactname .field--item"],
        ),
        "contact_email": _select_text(
            soup,
            ["#edit-group-contact-information .field--name-field-tender-contact-email .field--item"],
        ),
        "contact_phone": _select_text(
            soup,
            ["#edit-group-contact-information .field--name-field-tender-contact-phone .field--item"],
        ),
        "buying_organizations": buying_organizations,
        "trade_agreements": trade_agreements,
        "limited_tendering_reason": limited_tendering_reason,
        "documents": _extract_documents(soup),
        "related_notices": _extract_related_notices(soup),
    }

    data["raw_text"] = _build_structured_raw_text(data)
    return data
