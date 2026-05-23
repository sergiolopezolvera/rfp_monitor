import re

with open("app/services/export_service.py") as f:
    content = f.read()

# Modify `export_opportunities_to_excel` to accept `fit_level`
new_sig = """def export_opportunities_to_excel(
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
) -> ExportRunResult:"""

content = re.sub(
    r"def export_opportunities_to_excel\(\n    db: Session,\n    \*,\n    created_from: date \| None = None,\n    created_to: date \| None = None,\n    closing_after: date \| None = None,\n    source_name: str \| None = None,\n    status: str \| None = None,\n    fit_result: str \| None = None,\n    output_path: Path \| None = None,\n\) -> ExportRunResult:",
    new_sig,
    content,
    flags=re.MULTILINE
)

# Update fit_result logic
old_logic = """    if fit_result:
        filtered: list[Opportunity] = []
        for opp in opportunities:
            latest_analysis = _get_latest_analysis(opp)
            if fit_result == "fit" and latest_analysis and latest_analysis.is_fit is True:
                filtered.append(opp)
            elif fit_result == "not_fit" and latest_analysis and latest_analysis.is_fit is False:
                filtered.append(opp)
            elif fit_result == "unanalyzed" and latest_analysis is None:
                filtered.append(opp)
        opportunities = filtered"""

new_logic = """    if fit_result:
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
        opportunities = filtered"""

content = content.replace(old_logic, new_logic)

with open("app/services/export_service.py", "w") as f:
    f.write(content)
