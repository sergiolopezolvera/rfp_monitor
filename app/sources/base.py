from typing import Protocol

from app.schemas import FeedOpportunity


class BaseSourceConnector(Protocol):
    source_name: str

    def fetch_feed_items(self, limit: int = 50) -> list[FeedOpportunity]:
        ...