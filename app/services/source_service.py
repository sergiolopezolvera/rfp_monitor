from sqlalchemy.orm import Session

from app.repositories.sources import get_or_create_source, list_sources

DEFAULT_SOURCES = [
    {
        "name": "canadabuys",
        "base_url": "https://canadabuys.canada.ca",
        "is_active": True,
    },
    {
        "name": "merx",
        "base_url": "https://www.merx.com",
        "is_active": True,
    },
    {
        "name": "bidsandtenders",
        "base_url": "https://bids.bidsandtenders.ca",
        "is_active": True,
    },
    {
        "name": "ontario_tenders",
        "base_url": "https://ontariotenders.app.jaggaer.com",
        "is_active": True,
    },
    {
        "name": "nationtalk",
        "base_url": "https://nationtalk.ca",
        "is_active": True,
    },
        {
        "name": "chiefs_of_ontario",
        "base_url": "https://chiefs-of-ontario.org",
        "is_active": True,
    },


]


def seed_default_sources(db: Session) -> list[tuple[str, bool]]:
    """
    Ensure default sources exist.

    Returns a list of tuples:
    (source_name, was_created)
    """
    results: list[tuple[str, bool]] = []

    for source_data in DEFAULT_SOURCES:
        source, created = get_or_create_source(
            db,
            name=source_data["name"],
            base_url=source_data["base_url"],
            is_active=source_data["is_active"],
        )
        results.append((source.name, created))

    return results


def get_all_sources(db: Session):
    """Return all registered sources."""
    return list_sources(db)
