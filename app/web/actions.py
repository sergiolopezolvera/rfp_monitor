from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.services.analysis_service import AnalysisRunResult, analyze_opportunities
from app.services.scrape_service import (
    fetch_bidsandtenders_details,
    fetch_canadabuys_details,
    fetch_chiefs_of_ontario_details,
    fetch_merx_details,
    fetch_nationtalk_details,
    fetch_ontario_tenders_details,
    ingest_bidsandtenders_feed,
    ingest_canadabuys_feed,
    ingest_chiefs_of_ontario_feed,
    ingest_merx_feed,
    ingest_nationtalk_feed,
    ingest_ontario_tenders_feed,
)


ActionRunner = Callable[[Session, int], Any]


@dataclass(frozen=True)
class ActionFieldConfig:
    name: str = "limit"
    label: str = "Items"
    default: int = 10
    min_value: int = 1
    max_value: int = 200


@dataclass(frozen=True)
class SourceActionSet:
    ingest_feed: ActionRunner
    fetch_details: ActionRunner
    analyze: ActionRunner
    ingest_field: ActionFieldConfig = ActionFieldConfig(default=25)
    fetch_field: ActionFieldConfig = ActionFieldConfig(default=10)
    analyze_field: ActionFieldConfig = ActionFieldConfig(default=10)


def _run_analysis_for_source(source_name: str) -> ActionRunner:
    def _runner(db: Session, limit: int) -> AnalysisRunResult:
        return analyze_opportunities(db, limit=limit, source_name=source_name)

    return _runner


SOURCE_ACTIONS: dict[str, SourceActionSet] = {
    "canadabuys": SourceActionSet(
        ingest_feed=lambda db, limit: ingest_canadabuys_feed(db, limit=limit),
        fetch_details=lambda db, limit: fetch_canadabuys_details(db, limit=limit),
        analyze=_run_analysis_for_source("canadabuys"),
    ),
    "merx": SourceActionSet(
        ingest_feed=lambda db, limit: ingest_merx_feed(db, limit=limit),
        fetch_details=lambda db, limit: fetch_merx_details(db, limit=limit),
        analyze=_run_analysis_for_source("merx"),
    ),
    "bidsandtenders": SourceActionSet(
        ingest_feed=lambda db, limit: ingest_bidsandtenders_feed(db, limit=limit),
        fetch_details=lambda db, limit: fetch_bidsandtenders_details(db, limit=limit),
        analyze=_run_analysis_for_source("bidsandtenders"),
    ),
    "ontario_tenders": SourceActionSet(
        ingest_feed=lambda db, limit: ingest_ontario_tenders_feed(db, limit=limit),
        fetch_details=lambda db, limit: fetch_ontario_tenders_details(db, limit=limit),
        analyze=_run_analysis_for_source("ontario_tenders"),
    ),
    "nationtalk": SourceActionSet(
        ingest_feed=lambda db, limit: ingest_nationtalk_feed(db, limit=limit),
        fetch_details=lambda db, limit: fetch_nationtalk_details(db, limit=limit),
        analyze=_run_analysis_for_source("nationtalk"),
    ),
    "chiefs_of_ontario": SourceActionSet(
        ingest_feed=lambda db, pages: ingest_chiefs_of_ontario_feed(db, limit=50, pages=pages),
        fetch_details=lambda db, limit: fetch_chiefs_of_ontario_details(db, limit=limit),
        analyze=_run_analysis_for_source("chiefs_of_ontario"),
        ingest_field=ActionFieldConfig(
            name="pages",
            label="Pages",
            default=5,
            min_value=1,
            max_value=50,
        ),
    ),
}


def get_source_action_config(source_name: str) -> SourceActionSet | None:
    return SOURCE_ACTIONS.get(source_name)


def run_source_action(
    db: Session,
    source_name: str,
    action: str,
    value: int,
) -> tuple[str, str]:
    action_set = SOURCE_ACTIONS.get(source_name)
    if action_set is None:
        raise ValueError(f"Unsupported source: {source_name}")

    action_map = {
        "ingest_feed": action_set.ingest_feed,
        "fetch_details": action_set.fetch_details,
        "analyze": action_set.analyze,
    }
    runner = action_map.get(action)
    if runner is None:
        raise ValueError(f"Unsupported action: {action}")

    result = runner(db, value)
    return summarize_action_result(source_name, action, result, value=value), "success"


def summarize_action_result(source_name: str, action: str, result: Any, *, value: int) -> str:
    label = source_name.replace("_", " ")

    if action == "ingest_feed":
        created = sum(1 for _, was_created in result if was_created)
        existing = len(result) - created
        if source_name == "chiefs_of_ontario":
            return (
                f"{label}: feed ingest scanned {value} pages and processed {len(result)} opportunities "
                f"({created} new, {existing} existing)."
            )
        return (
            f"{label}: feed ingest processed {len(result)} opportunities "
            f"({created} new, {existing} existing)."
        )

    if action == "fetch_details":
        updated = sum(1 for _, status in result if status == "updated")
        blocked = sum(1 for _, status in result if status == "blocked")
        errors = sum(1 for _, status in result if status == "error")
        return (
            f"{label}: detail fetch processed {len(result)} opportunities "
            f"({updated} updated, {blocked} blocked, {errors} errors)."
        )

    if action == "analyze" and isinstance(result, AnalysisRunResult):
        return (
            f"{label}: analysis processed {result.processed} opportunities "
            f"({result.created} analyses created, {result.errors} errors)."
        )

    return f"{label}: action '{action}' completed."
