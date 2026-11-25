from datetime import UTC, datetime


def utcnow() -> datetime:
    """Current UTC time as a naive datetime, matching how timestamps are stored."""
    return datetime.now(UTC).replace(tzinfo=None)
