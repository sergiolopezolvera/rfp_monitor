from datetime import datetime

from pydantic import BaseModel, HttpUrl


class FeedOpportunity(BaseModel):
    # básicos
    title: str | None = None
    url: HttpUrl

    # texto auxiliar
    summary: str | None = None
    description: str | None = None

    # legacy / opcionales
    author: str | None = None

    # fechas
    date_published: datetime | None = None
    date_updated: datetime | None = None

    # 🔥 NUEVOS CAMPOS (CRÍTICOS)
    source_record_id: str | None = None
    organization: str | None = None
    closing_date: datetime | None = None
    bid_status: str | None = None
    reference_number: str | None = None
    category: str | None = None

    location: str | None = None
    notice_type: str | None = None
    category: str | None = None
    price: str | None = None
