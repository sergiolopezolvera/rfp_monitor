# RFP Monitor

Local RFP monitoring pipeline with a Typer CLI and a FastAPI review dashboard.

Sources: CanadaBuys, Merx, Bids & Tenders, Ontario Tenders, NationTalk and Chiefs of Ontario.
Each source has three steps: ingest the feed, fetch detail pages, and analyze fit with the LLM.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python main.py init-db
python main.py seed-sources
```

Configuration comes from environment variables or a local `.env` file (never commit it):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///data/rfp_monitor.db` | SQLAlchemy URL (SQLite locally, Postgres in the cloud) |
| `OPENAI_API_KEY` | — | Needed for the `analyze` step |
| `OPENAI_MODEL` | `gpt-4.1-mini` | Model used for fit analysis |
| `LOG_LEVEL` | `INFO` | Logs go to the console and `data/logs/app.log` |

## Run the CLI

```bash
python main.py --help
python main.py scrape-bidsandtenders-feed --limit 100
python main.py fetch-bidsandtenders-details --limit 20
```

## Run the Web UI Locally

```bash
uvicorn app.web.main:app --reload
```

Then open [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard).

The web UI is a thin control panel over the same pipeline: it reuses the SQLAlchemy models,
repositories, services, connectors and parsers. When an action fails, the message on the
Sources page names the error and the full traceback is in `data/logs/app.log`. Failed runs
also keep the reason in `scrape_runs.log_summary`.

## Troubleshooting Bids & Tenders

The connector reads `https://bids.bidsandtenders.ca/Module/Tenders/en` as a normal page to get
the search `NodeId` and anti-forgery token, then calls the JSON search endpoint
`/Module/Tenders/en/Tender/Search/{NodeId}`. If the portal changes, run:

```bash
python main.py diagnose-bidsandtenders
```

It reports which step fails (landing page, search, detail page), prints the keys of the
search rows, and saves the raw answers in `data/debug/bidsandtenders/`. A "blocked" error
means the portal answered a bot challenge; that happens more often from cloud servers than
from a home connection.

## Tests and lint

```bash
pytest -q
ruff check app main.py scripts tests
```

GitHub Actions runs both on every push to `main` and on pull requests.

## Maintenance scripts

One-off scripts live in `scripts/` and run as modules from the project root:

```bash
python -m scripts.migrate_sqlite_to_postgres   # copy local SQLite data into DATABASE_URL
python -m scripts.alter_category_column        # widen opportunities.category on Postgres
```

## Cloud Deployment

The app can run on a cloud platform (Render, Railway, Fly.io) with a managed PostgreSQL
database (e.g. Supabase or Render Postgres).

Containers are ephemeral: a SQLite file inside the container is lost on every deploy, so set
`DATABASE_URL` to a managed Postgres database in production.

### Environment Variables

- `APP_ENV`: `production`
- `DATABASE_URL`: Postgres connection string, e.g.
  `postgresql+psycopg2://postgres:YOUR_PASSWORD@db.supabase.co:5432/postgres`
- `OPENAI_API_KEY`: OpenAI API key for LLM analysis

### Deployment using Docker

The `Dockerfile` runs the FastAPI web UI on `0.0.0.0` and the port in `$PORT` (default 8000).

**Render / Railway Setup:**
1. Connect the GitHub repository to the cloud provider.
2. Select "Docker" as the deployment method.
3. Set the environment variables (including `DATABASE_URL`).
4. The platform builds the image and starts the server with
   `uvicorn app.web.main:app --host 0.0.0.0 --port $PORT`.
