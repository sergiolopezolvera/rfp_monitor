from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any

from bs4 import BeautifulSoup, Tag


ORDINAL_RE = re.compile(r"(\d+)(st|nd|rd|th)", re.IGNORECASE)

DEADLINE_RE = re.compile(
    r"(deadline|due|submit|submissions?|proposals?).{0,120}?"
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})",
    re.IGNORECASE | re.DOTALL,
)


def html_to_text(html: str) -> str:
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
    cleaned = [line for line in lines if line]
    return "\n".join(cleaned) if cleaned else None


def _text(node: Tag | None, separator: str = " ", multiline: bool = False) -> str | None:
    if node is None:
        return None

    raw = node.get_text(separator, strip=True)
    if multiline:
        return _normalize_multiline(raw)
    return _normalize_whitespace(raw)


def _extract_meta_content(soup: BeautifulSoup, selector: str) -> str | None:
    node = soup.select_one(selector)
    if not node:
        return None
    return _normalize_whitespace(node.get("content"))


def _parse_date(value: str | None) -> date | None:
    value = _normalize_whitespace(value)
    if not value:
        return None

    if "T" in value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass

    value = ORDINAL_RE.sub(r"\1", value)

    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:30], fmt).date()
        except ValueError:
            continue

    return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    title = (
        _text(soup.select_one("h1.entry-title"))
        or _text(soup.select_one("h2.entry-title.fusion-post-title"))
        or _extract_meta_content(soup, "meta[property='og:title']")
        or _text(soup.select_one("title"))
    )

    if title:
        title = title.replace(" - Chiefs of Ontario", "").strip()

    return title or None


def _extract_publication_date(soup: BeautifulSoup) -> date | None:
    published = (
        _extract_meta_content(soup, "meta[property='article:published_time']")
        or _extract_meta_content(soup, "meta[name='article:published_time']")
    )

    parsed = _parse_date(published)
    if parsed:
        return parsed

    meta_wrapper = soup.select_one(".fusion-meta-info-wrapper")
    if meta_wrapper:
        for span in meta_wrapper.select("span"):
            parsed = _parse_date(_text(span))
            if parsed:
                return parsed

    return None


def _extract_author(soup: BeautifulSoup) -> str | None:
    return (
        _extract_meta_content(soup, "meta[name='author']")
        or _text(soup.select_one(".fusion-meta-info-wrapper .fn a"))
    )


def _extract_category(soup: BeautifulSoup) -> str | None:
    values: list[str] = []

    for node in soup.select(".fusion-meta-info-wrapper a[rel='category tag']"):
        value = _text(node)
        if value and value not in values:
            values.append(value)

    return " | ".join(values) if values else None


def _extract_description(soup: BeautifulSoup) -> str | None:
    content_node = soup.select_one("article .post-content, .post-content")
    if content_node:
        return _text(content_node, separator="\n", multiline=True)

    return _extract_meta_content(soup, "meta[property='og:description']")


def _extract_full_text(soup: BeautifulSoup) -> str:
    sections: list[str] = []

    title = _extract_title(soup)
    if title:
        sections.append(title)

    meta_text = _text(soup.select_one(".fusion-meta-info-wrapper"), separator="\n", multiline=True)
    if meta_text:
        sections.append(meta_text)

    body_text = _text(soup.select_one("article .post-content, .post-content"), separator="\n", multiline=True)
    if body_text:
        sections.append(body_text)

    if sections:
        return "\n\n".join(sections)

    return html_to_text(str(soup))


# --- HIGH CONFIDENCE (explicit closing) ---
CLOSING_PATTERNS = [
    re.compile(
        r"(closing date(?: and time)?|rfp closing date(?: and time)?|closing date and time)[:\s]+"
        r"(?:date:\s*)?"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})",
        re.IGNORECASE,
    ),
]

# --- MEDIUM CONFIDENCE (submission language) ---
SUBMISSION_PATTERNS = [
    re.compile(
        r"(submission deadline|deadline to submit|the submission deadline is|proposals? due|submissions? due)[:\s]+"
        r"(?:\w+,\s*)?"  # allows "Friday,"
        r"(January|February|March|April|May|June|July|August|September|October|November|December)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})",
        re.IGNORECASE,
    ),
]

# --- LOW CONFIDENCE (fallback, very constrained) ---
FALLBACK_PATTERN = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})",
    re.IGNORECASE,
)


def _parse_date_parts(month: str, day: str, year: str) -> date | None:
    try:
        return datetime.strptime(f"{month} {day}, {year}", "%B %d, %Y").date()
    except ValueError:
        return None


def _extract_closing_date_from_text(text: str | None) -> date | None:
    if not text:
        return None

    # --- 1. HIGH CONFIDENCE ---
    for pattern in CLOSING_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        context = text[max(0, match.start() - 40) : match.end() + 40].lower()

        if any(bad in context for bad in ["issue date", "issued", "questions accepted"]):
            continue

        return _parse_date_parts(match.group(2), match.group(3), match.group(4))

    # --- 2. MEDIUM CONFIDENCE ---
    for pattern in SUBMISSION_PATTERNS:
        match = pattern.search(text)
        if match:
            return _parse_date_parts(match.group(2), match.group(3), match.group(4))

    # --- 3. FALLBACK (VERY CAREFUL) ---
    # Only accept fallback if it's near "deadline" context
    fallback_match = FALLBACK_PATTERN.search(text)
    if fallback_match:
        context_window = text[
            max(0, fallback_match.start() - 60) : fallback_match.end() + 60
        ].lower()

        if any(word in context_window for word in ["deadline", "submit", "closing"]):
            return _parse_date_parts(
                fallback_match.group(1),
                fallback_match.group(2),
                fallback_match.group(3),
            )

    return None


def _extract_links(soup: BeautifulSoup) -> list[str]:
    links: list[str] = []

    content_node = soup.select_one("article .post-content, .post-content")
    if not content_node:
        return links

    for anchor in content_node.select("a[href]"):
        href = anchor.get("href")
        if not href:
            continue

        label = _text(anchor)
        value = f"{label}: {href}" if label else href

        if value not in links:
            links.append(value)

    return links


def _build_structured_raw_text(data: dict[str, Any]) -> str:
    lines: list[str] = []

    scalar_fields = [
        ("Title", data.get("title")),
        ("Organization", data.get("organization")),
        ("Author", data.get("author")),
        (
            "Publication date",
            data.get("publication_date").isoformat()
            if data.get("publication_date")
            else None,
        ),
        (
            "Closing date",
            data.get("closing_date").isoformat()
            if data.get("closing_date")
            else None,
        ),
        ("Notice type", data.get("notice_type")),
        ("Category", data.get("category")),
    ]

    for label, value in scalar_fields:
        if value:
            lines.append(f"{label}: {value}")

    if data.get("description_raw"):
        lines.append(f"Description:\n{data['description_raw']}")

    if data.get("links"):
        lines.append("Links:")
        lines.extend(f"- {link}" for link in data["links"])

    return "\n\n".join(lines)


def parse_chiefs_of_ontario_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    full_text = _extract_full_text(soup)
    description = _extract_description(soup)

    closing_date = (
        _extract_closing_date_from_text(description)
        or _extract_closing_date_from_text(full_text)
    )

    data: dict[str, Any] = {
        "title": _extract_title(soup),
        "description_raw": description,
        "organization": "Chiefs of Ontario",
        "author": _extract_author(soup),
        "publication_date": _extract_publication_date(soup),
        "closing_date": closing_date,
        "notice_type": "Request for Proposals",
        "category": _extract_category(soup) or "RFP",
        "links": _extract_links(soup),
        "full_text": full_text,
    }

    structured = _build_structured_raw_text(data)

    data["raw_text"] = (
        f"{structured}\n\nFULL_TEXT:\n\n{full_text}"
        if structured and full_text
        else structured or full_text
    )

    return data
