from __future__ import annotations

from datetime import date, datetime
from typing import Any

from bs4 import BeautifulSoup


def _normalize(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.split()) or None


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None

    value = _normalize(value)

    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue

    return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    node = soup.select_one("h2.col-title")
    return _normalize(node.get_text()) if node else None


def _extract_meta_table(soup: BeautifulSoup) -> dict[str, str]:
    data: dict[str, str] = {}

    rows = soup.select(".tender-meta table tr")

    for row in rows:
        th = row.select_one("th")
        td = row.select_one("td")

        if not th or not td:
            continue

        key = _normalize(th.get_text())
        value = _normalize(td.get_text())

        if key and value:
            data[key.lower()] = value

    return data


def _extract_description(soup: BeautifulSoup) -> str | None:
    content = soup.select_one(".single-story-wrap")

    if not content:
        return None

    for tag in content.select("script, style"):
        tag.decompose()

    text = content.get_text("\n", strip=True)

    lines = [" ".join(line.split()) for line in text.splitlines()]
    lines = [line for line in lines if line]

    return "\n".join(lines) if lines else None


def _clean_organization(candidate: str | None) -> str | None:
    if not candidate:
        return None

    candidate = " ".join(candidate.split()).strip()

    cut_markers = [
        " Location:",
        " Closing Date:",
        " Deadline:",
        " RFQ No.:",
        " RFP No.:",
    ]

    for marker in cut_markers:
        if marker in candidate:
            candidate = candidate.split(marker, 1)[0].strip()

    if "The OFIFC" in candidate:
        candidate = "OFIFC"

    if "OFIFC Request for Proposals" in candidate:
        candidate = "OFIFC"

    if candidate.lower().startswith("ofifc request for proposals"):
        candidate = "OFIFC"

    candidate = candidate.strip(" -–—:;,.")
    return candidate or None  # ✅ CORRECTO (sin recursión)


def _extract_organization(description: str | None) -> str | None:
    if not description:
        return None

    lines = [line.strip() for line in description.splitlines() if line.strip()]

    label_patterns = [
        "issuing organization",
        "organization",
        "client",
        "agency",
    ]

    # 🔹 1. Intentar extracción estructurada
    for index, line in enumerate(lines[:20]):
        normalized = line.lower().rstrip(":").strip()

        if normalized in label_patterns and index + 1 < len(lines):
            candidate = lines[index + 1].strip()
            if 3 <= len(candidate) <= 150:
                return _clean_organization(candidate)

        for label in label_patterns:
            prefix = f"{label}:"
            if normalized.startswith(prefix):
                candidate = line.split(":", 1)[1].strip()
                if 3 <= len(candidate) <= 150:
                    return _clean_organization(candidate)

    # 🔹 2. Heurística por lenguaje natural
    head = " ".join(lines[:8])

    patterns = [
        " is seeking ",
        " is inviting ",
        " invites proposals ",
        " invites qualified ",
        " is accepting ",
        " requires ",
        " requests proposals ",
    ]

    for pattern in patterns:
        if pattern in head:
            candidate = head.split(pattern, 1)[0].strip()

            bad_phrases = [
                "request for proposals",
                "request for quotation",
                "rfp",
                "rfq",
                "consultant to",
            ]
            # Caso especial: OFIFC
            if "ofifc" in candidate.lower():
                return "OFIFC"

            if any(bad in candidate.lower() for bad in bad_phrases):
                continue

            if 3 <= len(candidate) <= 150:
                return _clean_organization(candidate)

    return None


def parse_nationtalk_notice(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")

    title = _extract_title(soup)
    meta = _extract_meta_table(soup)
    description = _extract_description(soup)
    organization = _extract_organization(description)

    data: dict[str, Any] = {
        "title": title,
        "description_raw": description,
        "organization": organization,
        "location": meta.get("region"),
        "publication_date": None,
        "closing_date": _parse_date(meta.get("deadline")),
        "notice_type": meta.get("type"),
        "category": meta.get("category"),
        "price": None,
    }

    lines = []

    if title:
        lines.append(f"Title: {title}")

    for k, v in meta.items():
        lines.append(f"{k.title()}: {v}")

    if description:
        lines.append(f"\nDescription:\n{description}")

    data["raw_text"] = "\n".join(lines)

    return data