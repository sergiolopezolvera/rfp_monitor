import re

with open("app/web/queries.py", "r") as f:
    content = f.read()

# I need to find the `list_opportunities_page` signature and update it
new_sig = """def list_opportunities_page(
    db: Session,
    *,
    page: int,
    source_name: str | None = None,
    status: str | None = None,
    fit_result: str | None = None,
    fit_level: str | None = None,
    created_from: date | None = None,
    created_to: date | None = None,
    closing_after: date | None = None,
) -> OpportunityPage:"""

content = re.sub(
    r"def list_opportunities_page\(\n    db: Session,\n    \*,\n    page: int,\n    source_name: str \| None = None,\n    status: str \| None = None,\n    fit_result: str \| None = None,\n    closing_from: date \| None = None,\n    closing_to: date \| None = None,\n\) -> OpportunityPage:",
    new_sig,
    content,
    flags=re.MULTILINE
)

# And then update the if conditions inside `list_opportunities_page`
old_conditions = """    if closing_from:
        base_stmt = base_stmt.where(Opportunity.closing_date >= closing_from)
    if closing_to:
        base_stmt = base_stmt.where(Opportunity.closing_date <= closing_to)
    if fit_result == "fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(True))
    elif fit_result == "not_fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(False))
    elif fit_result == "unanalyzed":
        base_stmt = base_stmt.where(latest_analysis.id.is_(None))"""

# Need to include `_date_start` and `_date_after` imports or do datetime logic if it's available. I'll just check `app/services/export_service.py` to see how it does it or write it myself inline.

# Let's import datetime and time to do _date_start and _date_after manually in queries if it's not imported already
new_conditions = """    if created_from:
        base_stmt = base_stmt.where(Opportunity.created_at >= datetime.combine(created_from, datetime.min.time()))
    if created_to:
        base_stmt = base_stmt.where(Opportunity.created_at < datetime.combine(created_to + timedelta(days=1), datetime.min.time()))
    if closing_after:
        base_stmt = base_stmt.where(Opportunity.closing_date >= closing_after)

    if fit_result == "fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(True))
        if fit_level == "3":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 3)
        elif fit_level == "2":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 2)
        elif fit_level == "1":
            base_stmt = base_stmt.where(latest_analysis.fit_score == 1)
    elif fit_result == "not_fit":
        base_stmt = base_stmt.where(latest_analysis.is_fit.is_(False))
    elif fit_result == "unanalyzed":
        base_stmt = base_stmt.where(latest_analysis.id.is_(None))"""

content = content.replace(old_conditions, new_conditions)

# Make sure datetime is imported if it's not already
if "from datetime import " not in content and "import datetime" not in content:
    content = "import datetime\n" + content
elif "from datetime import datetime" not in content and "import datetime" not in content:
    # Need to check imports carefully
    pass

with open("app/web/queries.py", "w") as f:
    f.write(content)
