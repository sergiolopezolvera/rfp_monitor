from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.logger import logger
from app.models import LLMAnalysis, Opportunity, Source

PROMPTS_DIR = Path("app/llm/prompts")
SYSTEM_PROMPT_PATH = PROMPTS_DIR / "system_prompt.txt"
FIRM_PROFILE_PATH = PROMPTS_DIR / "firm_profile.txt"
EXAMPLES_DB_PATH = PROMPTS_DIR / "examples_database.csv"


@dataclass
class AnalysisRunResult:
    processed: int = 0
    created: int = 0
    errors: int = 0


def _read_text_file(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required prompt/context file not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def _read_examples_csv(path: Path, max_rows: int | None = 40) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Examples database file not found: {path}")

    rows: list[str] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if max_rows is not None and i >= max_rows:
                break

            rows.append(
                json.dumps(
                    {
                        "title": row.get("Title"),
                        "organization": row.get("Organization"),
                        "fit": row.get("Fit"),
                        "level": row.get("Level"),
                        "rationale": row.get("Rationale"),
                    },
                    ensure_ascii=False,
                )
            )

    return "\n".join(rows)


def _build_system_message() -> str:
    system_prompt = _read_text_file(SYSTEM_PROMPT_PATH)
    firm_profile = _read_text_file(FIRM_PROFILE_PATH)
    examples = _read_examples_csv(EXAMPLES_DB_PATH, max_rows=40)

    return (
        f"{system_prompt}\n\n"
        "### FIRM PROFILE & SERVICES ###\n"
        f"{firm_profile}\n\n"
        "### EXAMPLES DATABASE ###\n"
        f"{examples}\n"
    )


def _build_user_message(opportunity: Opportunity) -> str:
    return (
        f"Title:{opportunity.title or ''}\n\n"
        f"Description:{opportunity.description_raw or ''}\n\n"
        f"Organization:{opportunity.organization or ''}\n\n"
        f"publicationDate:{opportunity.publication_date.isoformat() if opportunity.publication_date else ''}\n\n"
        f"closingDate:{opportunity.closing_date.isoformat() if opportunity.closing_date else ''}"
    )


def _fit_score_to_int(value: str | None) -> int | None:
    if value is None:
        return None

    normalized = value.strip().lower()
    mapping = {
        "high": 3,
        "medium": 2,
        "low": 1,
    }
    return mapping.get(normalized)


def _normalize_matched_services(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        cleaned = [str(v).strip() for v in value if str(v).strip()]
        return json.dumps(cleaned, ensure_ascii=False) if cleaned else None
    if isinstance(value, str):
        return json.dumps([value], ensure_ascii=False) if value.strip() else None
    return None


def _select_opportunities_for_analysis(
    db: Session,
    *,
    limit: int,
    source_name: str | None = None,
    include_statuses: tuple[str, ...] = ("detail_fetched",),
) -> list[Opportunity]:
    stmt = (
        select(Opportunity)
        .outerjoin(LLMAnalysis, LLMAnalysis.opportunity_id == Opportunity.id)
        .options(selectinload(Opportunity.analyses), selectinload(Opportunity.source))
        .where(Opportunity.status.in_(include_statuses), LLMAnalysis.id.is_(None))
    )

    if source_name:
        stmt = stmt.join(Opportunity.source).where(Source.name == source_name)

    stmt = stmt.order_by(Opportunity.updated_at.asc(), Opportunity.created_at.asc()).limit(limit)
    return list(db.scalars(stmt).all())


def analyze_opportunities(
    db: Session,
    *,
    limit: int = 10,
    source_name: str | None = None,
    prompt_version: str = "system_prompt_v1",
) -> AnalysisRunResult:
    system_message = _build_system_message()
    client = OpenAI(api_key=settings.openai_api_key)

    opportunities = _select_opportunities_for_analysis(db, limit=limit, source_name=source_name)
    result = AnalysisRunResult(processed=len(opportunities))

    for opp in opportunities:
        try:
            response = client.chat.completions.create(
                model=settings.openai_model,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_message},
                    {"role": "user", "content": _build_user_message(opp)},
                ],
            )

            raw_text = response.choices[0].message.content or "{}"
            parsed = json.loads(raw_text)

            analysis = LLMAnalysis(
                opportunity_id=opp.id,
                model=settings.openai_model,
                prompt_version=prompt_version,
                is_fit=parsed.get("isFit"),
                fit_score=_fit_score_to_int(parsed.get("fitScore")),
                reasoning=parsed.get("reasoning"),
                matched_services=_normalize_matched_services(parsed.get("matchedServices")),
                potential_concerns=parsed.get("potentialConcerns"),
                raw_response_json=json.dumps(parsed, ensure_ascii=False),
                token_input=getattr(response.usage, "prompt_tokens", None),
                token_output=getattr(response.usage, "completion_tokens", None),
            )

            db.add(analysis)
            db.commit()
            result.created += 1

        except Exception as exc:
            logger.exception("Failed to analyze opportunity %s: %s", opp.id, exc)
            db.rollback()
            result.errors += 1

    logger.info(
        "Opportunity analysis completed. processed=%s created=%s errors=%s",
        result.processed,
        result.created,
        result.errors,
    )
    return result
