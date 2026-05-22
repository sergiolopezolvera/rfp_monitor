# RFP Monitor

Local RFP monitoring pipeline with a Typer CLI and a FastAPI review dashboard.

## Run the CLI

```bash
python main.py --help
```

## Run the Web UI

```bash
uvicorn app.web.main:app --reload
```

Then open [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard).

The web UI is a thin control panel over the existing pipeline. It reuses the current SQLAlchemy models, repositories, services, source connectors, parsers, and SQLite database instead of replacing the CLI.
