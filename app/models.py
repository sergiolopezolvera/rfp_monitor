from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    opportunities: Mapped[list["Opportunity"]] = relationship(back_populates="source")
    scrape_runs: Mapped[list["ScrapeRun"]] = relationship(back_populates="source")

    def __repr__(self) -> str:
        return f"Source(id={self.id!r}, name={self.name!r})"


class Opportunity(Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        UniqueConstraint("source_id", "url", name="uq_opportunity_source_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)
    source_record_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    description_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    organization: Mapped[str | None] = mapped_column(String(255), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)

    publication_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    notice_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)

    raw_html_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    raw_text_path: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    hash_content: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False, index=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    source: Mapped["Source"] = relationship(back_populates="opportunities")
    analyses: Mapped[list["LLMAnalysis"]] = relationship(back_populates="opportunity")

    def __repr__(self) -> str:
        return f"Opportunity(id={self.id!r}, source_id={self.source_id!r}, url={self.url!r})"


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), nullable=False, index=True)

    status: Mapped[str] = mapped_column(String(50), default="started", nullable=False)
    items_found: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_inserted: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_updated: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    items_failed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    log_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    source: Mapped["Source"] = relationship(back_populates="scrape_runs")

    def __repr__(self) -> str:
        return f"ScrapeRun(id={self.id!r}, source_id={self.source_id!r}, status={self.status!r})"


class LLMAnalysis(Base):
    __tablename__ = "llm_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    opportunity_id: Mapped[int] = mapped_column(ForeignKey("opportunities.id"), nullable=False, index=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_fit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    fit_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    matched_services: Mapped[str | None] = mapped_column(Text, nullable=True)
    potential_concerns: Mapped[str | None] = mapped_column(Text, nullable=True)

    raw_response_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_estimate: Mapped[str | None] = mapped_column(String(50), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    opportunity: Mapped["Opportunity"] = relationship(back_populates="analyses")

    def __repr__(self) -> str:
        return f"LLMAnalysis(id={self.id!r}, opportunity_id={self.opportunity_id!r})"