from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
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
    days: int


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

    header = [
        "id",
        "source",
        "organization",
        "url",
        "description",
        "publication_date",
        "closing_date",
        "fit_score",
        "reasoning",
        "matched_services",
    ]

    rows: list[list[Any]] = [header]

    exported_count = 0

    for opp in opportunities:
        latest_analysis = _get_latest_analysis(opp)

        if latest_analysis is None:
            continue

        if latest_analysis.is_fit != 1:
            continue

        rows.append(
            [
                opp.id,
                opp.source.name if opp.source else None,
                opp.organization,
                opp.url,
                opp.description_raw,
                opp.publication_date,
                opp.closing_date,
                latest_analysis.fit_score,
                latest_analysis.reasoning,
                latest_analysis.matched_services,
            ]
        )

        exported_count += 1

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