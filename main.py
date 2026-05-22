import typer
from rich import print

from app.config import settings
from app.db import Base, SessionLocal, engine
from app.logger import logger
import app.models  # noqa: F401
from app.services.source_service import get_all_sources, seed_default_sources
from app.repositories.opportunities import list_opportunities as repo_list_opportunities
from app.services.scrape_service import (
    fetch_canadabuys_details,
    fetch_merx_details,
    fetch_bidsandtenders_details,
    ingest_canadabuys_feed,
    ingest_merx_feed,
    ingest_bidsandtenders_feed,
    fetch_ontario_tenders_details,
    ingest_ontario_tenders_feed,
    ingest_nationtalk_feed,
    fetch_nationtalk_details,
    ingest_chiefs_of_ontario_feed,
    fetch_chiefs_of_ontario_details,
)
from app.services.analysis_service import analyze_opportunities
from app.services.export_service import export_new_opportunities_to_excel

app = typer.Typer(help="RFP monitoring CLI")


@app.command()
def info() -> None:
    """Show current application configuration."""
    settings.ensure_directories()

    print("[bold green]RFP Monitor[/bold green]")
    print(f"Environment: {settings.app_env}")
    print(f"Database: {settings.database_url}")
    print(f"OpenAI model: {settings.openai_model}")
    print(f"Data dir: {settings.data_dir}")
    print(f"Raw dir: {settings.raw_dir}")
    print(f"Parsed dir: {settings.parsed_dir}")
    print(f"Export dir: {settings.export_dir}")
    print(f"Log dir: {settings.log_dir}")

    logger.info("Displayed application info.")


@app.command()
def init() -> None:
    """Initialize local project directories."""
    settings.ensure_directories()
    logger.info("Project directories initialized.")
    print("[green]Directories initialized successfully.[/green]")


@app.command("init-db")
def init_db() -> None:
    """Create database tables."""
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully.")
    print("[green]Database initialized successfully.[/green]")


@app.command("seed-sources")
def seed_sources() -> None:
    """Insert default procurement sources."""
    with SessionLocal() as db:
        results = seed_default_sources(db)

    print("[bold green]Seed results[/bold green]")
    for source_name, created in results:
        status = "created" if created else "already existed"
        print(f"- {source_name}: {status}")

    logger.info("Default sources seeded successfully.")


@app.command("list-sources")
def list_sources() -> None:
    """List all registered sources."""
    with SessionLocal() as db:
        sources = get_all_sources(db)

    if not sources:
        print("[yellow]No sources found.[/yellow]")
        return

    print("[bold green]Registered sources[/bold green]")
    for source in sources:
        print(
            f"- id={source.id} | name={source.name} | active={source.is_active} | base_url={source.base_url}"
        )

    logger.info("Listed registered sources.")

@app.command("scrape-canadabuys-feed")
def scrape_canadabuys_feed(limit: int = 50) -> None:
    """Fetch CanadaBuys RSS items and store new opportunities."""
    with SessionLocal() as db:
        results = ingest_canadabuys_feed(db, limit=limit)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]CanadaBuys feed ingestion[/bold green]")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-canadabuys-feed command.")


@app.command("scrape-merx-feed")
def scrape_merx_feed(limit: int = 50) -> None:
    """Fetch MERX solicitation URLs and store new opportunities."""
    with SessionLocal() as db:
        results = ingest_merx_feed(db, limit=limit)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]MERX feed ingestion[/bold green]")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-merx-feed command.")

@app.command("scrape-bidsandtenders-feed")
def scrape_bidsandtenders_feed(limit: int = 50) -> None:
    """Fetch Bids & Tenders opportunities and store new ones."""
    with SessionLocal() as db:
        results = ingest_bidsandtenders_feed(db, limit=limit)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]Bids & Tenders feed ingestion[/bold green]")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-bidsandtenders-feed command.")


@app.command("scrape-ontario-tenders-feed")
def scrape_ontario_tenders_feed(limit: int = 50) -> None:
    """Fetch Ontario Tenders opportunities and store new ones."""
    with SessionLocal() as db:
        results = ingest_ontario_tenders_feed(db, limit=limit)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]Ontario Tenders feed ingestion[/bold green]")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-ontario-tenders-feed command.")

@app.command("scrape-nationtalk-feed")
def scrape_nationtalk_feed(limit: int = 50) -> None:
    """Fetch NationTalk tenders and store new opportunities."""
    with SessionLocal() as db:
        results = ingest_nationtalk_feed(db, limit=limit)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]NationTalk feed ingestion[/bold green]")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-nationtalk-feed command.")

@app.command("list-opportunities")
def list_opportunities(
    source_name: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> None:
    """List stored opportunities."""
    with SessionLocal() as db:
        source_id = None
        if source_name:
            from app.repositories.sources import get_source_by_name

            source = get_source_by_name(db, source_name)
            if source is None:
                print(f"[red]Source not found:[/red] {source_name}")
                raise typer.Exit(code=1)
            source_id = source.id

        opportunities = repo_list_opportunities(
            db,
            source_id=source_id,
            status=status,
            limit=limit,
        )

    if not opportunities:
        print("[yellow]No opportunities found.[/yellow]")
        return

    print("[bold green]Stored opportunities[/bold green]")
    for opp in opportunities:
        print(
            f"- id={opp.id} | source_id={opp.source_id} | status={opp.status} | "
            f"title={opp.title} | url={opp.url}"
        )

    logger.info("Listed opportunities.")


@app.command("fetch-canadabuys-details")
def fetch_canadabuys_details_command(
    limit: int = 3,
    min_interval_seconds: float = 20.0,
    retry_wait_seconds: float = 45.0,
    retry_error_after_minutes: int = 60,
    retry_blocked_after_minutes: int = 360,
) -> None:
    """Fetch CanadaBuys detail pages very gradually to reduce blocking."""
    with SessionLocal() as db:
        results = fetch_canadabuys_details(
            db,
            limit=limit,
            min_interval_seconds=min_interval_seconds,
            retry_wait_seconds=retry_wait_seconds,
            retry_error_after_minutes=retry_error_after_minutes,
            retry_blocked_after_minutes=retry_blocked_after_minutes,
        )

    updated = sum(1 for _, status in results if status == "updated")
    blocked = sum(1 for _, status in results if status == "blocked")
    errors = sum(1 for _, status in results if status == "error")

    print("[bold green]CanadaBuys detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Min interval seconds: {min_interval_seconds}")
    print(f"Retry wait seconds: {retry_wait_seconds}")
    print(f"Retry detail_error after minutes: {retry_error_after_minutes}")
    print(f"Retry detail_blocked after minutes: {retry_blocked_after_minutes}")
    print(f"Updated: {updated}")
    print(f"Blocked: {blocked}")
    print(f"Errors: {errors}")

    logger.info("Completed fetch-canadabuys-details command.")

@app.command("fetch-merx-details")
def fetch_merx_details_command(limit: int = 10) -> None:
    """Fetch detail pages for discovered MERX opportunities."""
    with SessionLocal() as db:
        results = fetch_merx_details(db, limit=limit)

    updated = sum(1 for _, status in results if status == "updated")
    blocked = sum(1 for _, status in results if status == "blocked")
    errors = sum(1 for _, status in results if status == "error")

    print("[bold green]MERX detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Updated: {updated}")
    print(f"Blocked: {blocked}")
    print(f"Errors: {errors}")

    logger.info("Completed fetch-merx-details command.")

@app.command("analyze-opportunities")
def analyze_opportunities_command(limit: int = 10) -> None:
    """Analyze fetched opportunities with the LLM and store results."""
    with SessionLocal() as db:
        results = analyze_opportunities(db, limit=limit)

    print("[bold green]Opportunity analysis[/bold green]")
    print(f"Processed: {results.processed}")
    print(f"Created analyses: {results.created}")
    print(f"Errors: {results.errors}")

    logger.info("Completed analyze-opportunities command.")

@app.command("fetch-bidsandtenders-details")
def fetch_bidsandtenders_details_command(limit: int = 10) -> None:
    """Fetch detail pages for discovered Bids & Tenders opportunities."""
    with SessionLocal() as db:
        results = fetch_bidsandtenders_details(db, limit=limit)

    updated = sum(1 for _, status in results if status == "updated")
    errors = sum(1 for _, status in results if status == "error")

    print("[bold green]Bids & Tenders detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Updated: {updated}")
    print(f"Errors: {errors}")

    logger.info("Completed fetch-bidsandtenders-details command.")


@app.command("fetch-ontario-tenders-details")
def fetch_ontario_tenders_details_command(limit: int = 10) -> None:
    """Fetch detail pages for discovered Ontario Tenders opportunities."""
    with SessionLocal() as db:
        results = fetch_ontario_tenders_details(db, limit=limit)

    updated = sum(1 for _, status in results if status == "updated")
    errors = sum(1 for _, status in results if status == "error")

    print("[bold green]Ontario Tenders detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Updated: {updated}")
    print(f"Errors: {errors}")

    logger.info("Completed fetch-ontario-tenders-details command.")

@app.command("fetch-nationtalk-details")
def fetch_nationtalk_details_command(limit: int = 20) -> None:
    """Fetch NationTalk tender detail pages and update stored opportunities."""
    with SessionLocal() as db:
        results = fetch_nationtalk_details(db, limit=limit)

    updated_count = sum(1 for _, status in results if status == "updated")
    error_count = sum(1 for _, status in results if status == "error")

    print("[bold green]NationTalk detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Updated: {updated_count}")
    print(f"Errors: {error_count}")

    logger.info("Completed fetch-nationtalk-details command.")

@app.command("scrape-chiefs-of-ontario-feed")
def scrape_chiefs_of_ontario_feed(limit: int = 50, pages: int = 5) -> None:
    """Fetch Chiefs of Ontario updates pages and store RFP-like posts."""
    with SessionLocal() as db:
        results = ingest_chiefs_of_ontario_feed(db, limit=limit, pages=pages)

    created_count = sum(1 for _, created in results if created)
    existing_count = len(results) - created_count

    print("[bold green]Chiefs of Ontario feed ingestion[/bold green]")
    print(f"Pages scanned: {pages}")
    print(f"Total items processed: {len(results)}")
    print(f"New items: {created_count}")
    print(f"Existing items: {existing_count}")

    logger.info("Completed scrape-chiefs-of-ontario-feed command.")


@app.command("fetch-chiefs-of-ontario-details")
def fetch_chiefs_of_ontario_details_command(limit: int = 20) -> None:
    """Fetch Chiefs of Ontario detail pages."""
    with SessionLocal() as db:
        results = fetch_chiefs_of_ontario_details(db, limit=limit)

    updated_count = sum(1 for _, status in results if status == "detail_fetched")
    error_count = sum(1 for _, status in results if status == "detail_error")

    print("[bold green]Chiefs of Ontario detail fetch[/bold green]")
    print(f"Processed: {len(results)}")
    print(f"Updated: {updated_count}")
    print(f"Errors: {error_count}")

    logger.info("Completed fetch-chiefs-of-ontario-details command.")


@app.command("export-new-opportunities")
def export_new_opportunities_command(days: int = 7) -> None:
    """Export only newly discovered opportunities from the last N days to Excel."""
    with SessionLocal() as db:
        result = export_new_opportunities_to_excel(db, days=days)

    print("[bold green]New opportunities Excel export[/bold green]")
    print(f"Days included: {result.days}")
    print(f"Rows exported: {result.exported_count}")
    print(f"Output file: {result.output_path}")

    logger.info("Completed export-new-opportunities command.")

if __name__ == "__main__":
    app()
