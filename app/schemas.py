from datetime import datetime

from pydantic import BaseModel, HttpUrl


class FeedOpportunity(BaseModel):
    """One opportunity as listed by a source feed, before detail-page processing."""

    title: str | None = None
    url: HttpUrl

    summary: str | None = None
    description: str | None = None
    author: str | None = None

    date_published: datetime | None = None
    date_updated: datetime | None = None
    closing_date: datetime | None = None

    source_record_id: str | None = None
    organization: str | None = None
    bid_status: str | None = None
    reference_number: str | None = None
    category: str | None = None
    location: str | None = None
    notice_type: str | None = None
    price: str | None = None
