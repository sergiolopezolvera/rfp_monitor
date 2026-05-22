from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source


def get_source_by_name(db: Session, name: str) -> Source | None:
    """Return a source by its unique name."""
    stmt = select(Source).where(Source.name == name)
    return db.scalar(stmt)


def list_sources(db: Session) -> list[Source]:
    """Return all sources ordered by name."""
    stmt = select(Source).order_by(Source.name.asc())
    return list(db.scalars(stmt).all())


def create_source(
    db: Session,
    *,
    name: str,
    base_url: str | None = None,
    is_active: bool = True,
) -> Source:
    """Create and persist a new source."""
    source = Source(
        name=name,
        base_url=base_url,
        is_active=is_active,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_or_create_source(
    db: Session,
    *,
    name: str,
    base_url: str | None = None,
    is_active: bool = True,
) -> tuple[Source, bool]:
    """Return an existing source or create it if it does not exist."""
    existing = get_source_by_name(db, name)
    if existing is not None:
        return existing, False

    created = create_source(
        db,
        name=name,
        base_url=base_url,
        is_active=is_active,
    )
    return created, True