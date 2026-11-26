"""Plain-language labels for the web UI.

Database values stay as they are (``detail_fetched``, ``chiefs_of_ontario``...); these
helpers only change what people read on screen.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.utils.time import utcnow

SOURCE_LABELS = {
    "canadabuys": "CanadaBuys",
    "merx": "MERX",
    "bidsandtenders": "Bids & Tenders",
    "ontario_tenders": "Ontario Tenders",
    "nationtalk": "NationTalk",
    "chiefs_of_ontario": "Chiefs of Ontario",
}

# status -> (label, tone, explanation)
STATUS_LABELS = {
    "discovered": ("Details pending", "warn", "Found in the listing; the full posting has not been read yet."),
    "detail_fetched": ("Ready", "success", "The full posting was read and can be analyzed."),
    "detail_error": ("Details failed", "danger", "Reading the full posting failed. It will be retried."),
    "detail_blocked": ("Blocked by site", "danger", "The site refused the request. It will be retried later."),
    "new": ("New", "warn", "Not processed yet."),
}

FIT_FILTERS = {
    "good": ("fit", ""),
    "high": ("fit", "3"),
    "medium": ("fit", "2"),
    "low": ("fit", "1"),
    "not_fit": ("not_fit", ""),
    "unanalyzed": ("unanalyzed", ""),
}


def source_label(name: str | None) -> str:
    if not name:
        return "Unknown source"
    return SOURCE_LABELS.get(name, name.replace("_", " ").title())


def status_label(status: str | None) -> str:
    if not status:
        return "Unknown"
    return STATUS_LABELS.get(status, (status.replace("_", " ").capitalize(), "", ""))[0]


def status_tone(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", ("", "", ""))[1]


def status_help(status: str | None) -> str:
    return STATUS_LABELS.get(status or "", ("", "", ""))[2]


def fit_label(analysis: Any) -> str:
    if analysis is None:
        return "Not analyzed"
    if analysis.is_fit is False:
        return "Not a fit"
    return {3: "High fit", 2: "Medium fit", 1: "Low fit"}.get(analysis.fit_score, "Fit")


def fit_tone(analysis: Any) -> str:
    if analysis is None:
        return ""
    if analysis.is_fit is False:
        return "muted"
    return {3: "success", 2: "success", 1: "info"}.get(analysis.fit_score, "info")


def closing_text(closing: date | None) -> str:
    if closing is None:
        return "No date"
    days = (closing - date.today()).days
    if days < 0:
        return "Closed"
    if days == 0:
        return "Closes today"
    if days == 1:
        return "Tomorrow"
    return f"In {days} days"


def closing_tone(closing: date | None) -> str:
    if closing is None:
        return ""
    days = (closing - date.today()).days
    if days < 0:
        return "muted"
    if days <= 7:
        return "warn"
    return ""


def fit_filter_to_params(fit: str | None) -> tuple[str | None, str | None]:
    """Map the single "Fit" dropdown to the (fit_result, fit_level) pair used by queries."""
    if not fit:
        return None, None
    result, level = FIT_FILTERS.get(fit, (None, None))
    return result or None, level or None


def time_ago(value: datetime | None) -> str:
    """Describe a stored UTC timestamp relative to now ("3 hours ago")."""
    if not isinstance(value, datetime):
        return "never"
    seconds = int((utcnow() - value).total_seconds())
    if seconds < 60:
        return "just now"
    for size, unit in ((86400, "day"), (3600, "hour"), (60, "minute")):
        if seconds >= size:
            count = seconds // size
            return f"{count} {unit}{'s' if count != 1 else ''} ago"
    return "just now"


def register(env) -> None:
    env.filters["time_ago"] = time_ago
    env.filters["source_label"] = source_label
    env.filters["status_label"] = status_label
    env.filters["status_tone"] = status_tone
    env.filters["status_help"] = status_help
    env.filters["closing_text"] = closing_text
    env.filters["closing_tone"] = closing_tone
    env.globals["fit_label"] = fit_label
    env.globals["fit_tone"] = fit_tone
