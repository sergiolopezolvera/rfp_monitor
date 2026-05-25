import os
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models import Source, Opportunity, ScrapeRun, LLMAnalysis, Base

def migrate():
    # Postgres connection
    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        print("DATABASE_URL not set.")
        sys.exit(1)

    print(f"Migrating to {pg_url}...")

    # We need connect_args to make sure we use SSL to connect to Render's postgres instances from within python, bypassing sqlalchemy's issues
    pg_engine = create_engine(pg_url, connect_args={"sslmode": "require"})

    # Ensure tables exist
    Base.metadata.create_all(pg_engine)

    PgSession = sessionmaker(bind=pg_engine)
    pg_session = PgSession()

    # Check if we actually need to migrate
    opp_count = pg_session.query(Opportunity).count()
    if opp_count > 0:
        print(f"PostgreSQL database already has {opp_count} opportunities. Skipping migration.")
        return

    # SQLite connection
    # Changed path to local relative path since it's checked into repo root
    sqlite_url = "sqlite:///rfp_monitor.db"
    sqlite_engine = create_engine(sqlite_url)
    SqliteSession = sessionmaker(bind=sqlite_engine)
    sqlite_session = SqliteSession()


    print("Migrating Sources...")
    sources = sqlite_session.query(Source).all()
    source_map = {}
    for source in sources:
        existing = pg_session.query(Source).filter(Source.name == source.name).first()
        if not existing:
            new_source = Source(
                name=source.name,
                base_url=source.base_url,
                is_active=source.is_active,
                created_at=source.created_at,
                updated_at=source.updated_at
            )
            pg_session.add(new_source)
            pg_session.commit()
            source_map[source.id] = new_source.id
        else:
            source_map[source.id] = existing.id

    print("Migrating Opportunities...")
    opportunities = sqlite_session.query(Opportunity).all()
    opp_map = {}
    for opp in opportunities:
        if opp.source_id not in source_map:
            continue

        new_source_id = source_map[opp.source_id]
        existing = pg_session.query(Opportunity).filter(Opportunity.url == opp.url).first()
        if not existing:
            new_opp = Opportunity(
                source_id=new_source_id,
                source_record_id=opp.source_record_id,
                url=opp.url,
                title=opp.title,
                description_raw=opp.description_raw,
                organization=opp.organization,
                location=opp.location,
                publication_date=opp.publication_date,
                closing_date=opp.closing_date,
                notice_type=opp.notice_type,
                category=opp.category,
                raw_html_path=opp.raw_html_path,
                raw_text_path=opp.raw_text_path,
                hash_content=opp.hash_content,
                status=opp.status,
                created_at=opp.created_at,
                updated_at=opp.updated_at
            )
            pg_session.add(new_opp)
            pg_session.commit()
            opp_map[opp.id] = new_opp.id
        else:
            opp_map[opp.id] = existing.id

    print("Migrating LLM Analyses...")
    analyses = sqlite_session.query(LLMAnalysis).all()
    for analysis in analyses:
        if analysis.opportunity_id not in opp_map:
            continue

        new_opp_id = opp_map[analysis.opportunity_id]

        # We assume if an opportunity has an analysis in PG, we shouldn't duplicate it.
        # But a single opportunity might have multiple. We can check if one with the same model/prompt version exists.
        existing = pg_session.query(LLMAnalysis).filter(
            LLMAnalysis.opportunity_id == new_opp_id,
            LLMAnalysis.model == analysis.model,
            LLMAnalysis.prompt_version == analysis.prompt_version
        ).first()

        if not existing:
            new_analysis = LLMAnalysis(
                opportunity_id=new_opp_id,
                model=analysis.model,
                prompt_version=analysis.prompt_version,
                is_fit=analysis.is_fit,
                fit_score=analysis.fit_score,
                reasoning=analysis.reasoning,
                matched_services=analysis.matched_services,
                potential_concerns=analysis.potential_concerns,
                raw_response_json=analysis.raw_response_json,
                token_input=analysis.token_input,
                token_output=analysis.token_output,
                cost_estimate=analysis.cost_estimate,
                created_at=analysis.created_at
            )
            pg_session.add(new_analysis)
            pg_session.commit()

    print("Migrating Scrape Runs...")
    runs = sqlite_session.query(ScrapeRun).all()
    for run in runs:
        if run.source_id not in source_map:
            continue

        new_source_id = source_map[run.source_id]

        # Avoid duplicating scrape runs entirely. We can just check by started_at timestamp.
        existing = pg_session.query(ScrapeRun).filter(
            ScrapeRun.source_id == new_source_id,
            ScrapeRun.started_at == run.started_at
        ).first()

        if not existing:
            new_run = ScrapeRun(
                source_id=new_source_id,
                status=run.status,
                items_found=run.items_found,
                items_inserted=run.items_inserted,
                items_updated=run.items_updated,
                items_failed=run.items_failed,
                log_summary=run.log_summary,
                started_at=run.started_at,
                finished_at=run.finished_at
            )
            pg_session.add(new_run)
            pg_session.commit()

    print("Migration complete!")

if __name__ == "__main__":
    migrate()
