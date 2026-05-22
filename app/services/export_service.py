from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
import re
from typing import Any
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.logger import logger
from app.models import Opportunity


@dataclass
class ExportRunResult:
    output_path: Path
    exported_count: int
    days: int | None = None


def _excel_column_name(index: int) -> str:
    result = ""
    current = index

    while current > 0:
        current, remainder = divmod(current - 1, 26)
        result = chr(65 + remainder) + result

    return result


def _stringify_cell(value: Any) -> str:
    if value is None:
        return ""

    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"

    if hasattr(value, "isoformat"):
        return value.isoformat()

    return str(value)


def _build_sheet_xml(rows: list[list[Any]]) -> str:
    xml_rows: list[str] = []

    for row_index, row in enumerate(rows, start=1):
        cells: list[str] = []

        for col_index, value in enumerate(row, start=1):
            ref = f"{_excel_column_name(col_index)}{row_index}"
            cell_text = escape(_stringify_cell(value))
            cells.append(
                f'<c r="{ref}" t="inlineStr">'
                f'<is><t xml:space="preserve">{cell_text}</t></is>'
                f"</c>"
            )

        xml_rows.append(f'<row r="{row_index}">{"".join(cells)}</row>')

    dimension_ref = (
        f"A1:{_excel_column_name(len(rows[0]))}{len(rows)}"
        if rows
        else "A1:A1"
    )

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="{dimension_ref}"/>'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="15"/>'
        "<sheetData>"
        f"{''.join(xml_rows)}"
        "</sheetData>"
        "</worksheet>"
    )


def _write_xlsx(output_path: Path, rows: list[list[Any]]) -> None:
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="New Opportunities" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )

    root_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )

    content_types_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        "</Types>"
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with ZipFile(output_path, "w", compression=ZIP_DEFLATED) as workbook:
        workbook.writestr("[Content_Types].xml", content_types_xml)
        workbook.writestr("_rels/.rels", root_rels_xml)
        workbook.writestr("xl/workbook.xml", workbook_xml)
        workbook.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        workbook.writestr("xl/worksheets/sheet1.xml", _build_sheet_xml(rows))


def _get_latest_analysis(opportunity: Opportunity):
    if not opportunity.analyses:
        return None

    return sorted(
        opportunity.analyses,
        key=lambda analysis: analysis.created_at,
        reverse=True,
    )[0]


def _date_start(value: date) -> datetime:
    return datetime.combine(value, time.min)


def _date_after(value: date) -> datetime:
    return datetime.combine(value + timedelta(days=1), time.min)


def _safe_filename_part(value: str | None) -> str:
    if not value:
        return "all"
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip()).strip("_")
    return cleaned or "all"


def _opportunity_export_rows(opportunities: list[Opportunity]) -> tuple[list[list[Any]], int]:
    header = [
        "id",
        "source",
        "title",
        "organization",
        "url",
        "description",
        "publication_date",
        "closing_date",
        "created_at",
        "status",
        "is_fit",
        "fit_score",
        "reasoning",
        "matched_services",
        "potential_concerns",
    ]

    rows: list[list[Any]] = [header]

    for opp in opportunities:
        latest_analysis = _get_latest_analysis(opp)
        rows.append(
            [
                opp.id,
                opp.source.name if opp.source else None,
                opp.title,
                opp.organization,
                opp.url,
                opp.description_raw,
                opp.publication_date,
                opp.closing_date,
                opp.created_at,
                opp.status,
                latest_analysis.is_fit if latest_analysis else None,
                latest_analysis.fit_score if latest_analysis else None,
                latest_analysis.reasoning if latest_analysis else None,
                latest_analysis.matched_services if latest_analysis else None,
                latest_analysis.potential_concerns if latest_analysis else None,
            ]
        )

    return rows, len(opportunities)


def export_opportunities_to_excel(
    db: Session,
    *,
    created_from: date | None = None,
    created_to: date | None = None,
    closing_after: date | None = None,
    source_name: str | None = None,
    status: str | None = None,
    fit_result: str | None = None,
    fit_level: str | None = None,
    output_path: Path | None = None,
) -> ExportRunResult:
    settings.ensure_directories()

    stmt = (
        select(Opportunity)
        .options(
            selectinload(Opportunity.source),
            selectinload(Opportunity.analyses),
        )
        .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
    )

    if created_from:
        stmt = stmt.where(Opportunity.created_at >= _date_start(created_from))
    if created_to:
        stmt = stmt.where(Opportunity.created_at < _date_after(created_to))
    if closing_after:
        stmt = stmt.where(Opportunity.closing_date >= closing_after)
    if source_name:
        stmt = stmt.where(Opportunity.source.has(name=source_name))
    if status:
        stmt = stmt.where(Opportunity.status == status)

    opportunities = list(db.scalars(stmt).all())

    if fit_result:
        filtered: list[Opportunity] = []
        for opp in opportunities:
            latest_analysis = _get_latest_analysis(opp)
            if fit_result == "fit" and latest_analysis and latest_analysis.is_fit is True:
                if fit_level:
                    if str(latest_analysis.fit_score) == fit_level:
                        filtered.append(opp)
                else:
                    filtered.append(opp)
            elif fit_result == "not_fit" and latest_analysis and latest_analysis.is_fit is False:
                filtered.append(opp)
            elif fit_result == "unanalyzed" and latest_analysis is None:
                filtered.append(opp)
        opportunities = filtered

    if output_path is None:
        created_part = "all_dates"
        if created_from or created_to:
            created_part = (
                f"{created_from.isoformat() if created_from else 'start'}_"
                f"to_{created_to.isoformat() if created_to else 'today'}"
            )
        filename = (
            "opportunities_"
            f"{_safe_filename_part(source_name)}_"
            f"{_safe_filename_part(status)}_"
            f"{_safe_filename_part(fit_result)}_"
            f"{created_part}_"
            f"{datetime.utcnow():%Y%m%d_%H%M%S}.xlsx"
        )
        output_path = settings.export_dir / filename

    rows, exported_count = _opportunity_export_rows(opportunities)
    _write_xlsx(output_path, rows)

    logger.info(
        "Opportunities Excel export completed. exported=%s source=%s status=%s fit=%s "
        "created_from=%s created_to=%s closing_after=%s path=%s",
        exported_count,
        source_name,
        status,
        fit_result,
        created_from,
        created_to,
        closing_after,
        output_path,
    )

    return ExportRunResult(output_path=output_path, exported_count=exported_count)


def export_new_opportunities_to_excel(
    db: Session,
    *,
    days: int = 7,
    source_name: str | None = None,
    output_path: Path | None = None,
) -> ExportRunResult:
    if days <= 0:
        raise ValueError("days must be a positive integer.")

    settings.ensure_directories()

    cutoff = datetime.utcnow() - timedelta(days=days)

    stmt = (
        select(Opportunity)
        .options(
            selectinload(Opportunity.source),
            selectinload(Opportunity.analyses),
        )
        .where(Opportunity.created_at >= cutoff)
        .order_by(Opportunity.created_at.desc(), Opportunity.id.desc())
    )

    opportunities = list(db.scalars(stmt).all())

    if source_name:
        opportunities = [
            opp
            for opp in opportunities
            if opp.source and opp.source.name == source_name
        ]

    if output_path is None:
        suffix = source_name or "all_sources"
        filename = (
            f"new_opportunities_non_fit_last_{days}_days_"
            f"{suffix}_{datetime.utcnow():%Y-%m-%d}.xlsx"
        )
        output_path = settings.export_dir / filename

    exported: list[Opportunity] = []

    for opp in opportunities:
        latest_analysis = _get_latest_analysis(opp)

        if latest_analysis is None:
            continue

        if latest_analysis.is_fit != 1:
            continue

        exported.append(opp)

    rows, exported_count = _opportunity_export_rows(exported)
    _write_xlsx(output_path, rows)

    logger.info(
        "New non-fit opportunities Excel export completed. days=%s source=%s exported=%s path=%s",
        days,
        source_name,
        exported_count,
        output_path,
    )

    return ExportRunResult(
        output_path=output_path,
        exported_count=exported_count,
        days=days,
    )
