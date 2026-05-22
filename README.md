# RFP Monitor

Local RFP monitoring pipeline with a Typer CLI and a FastAPI review dashboard.

## Run the CLI

```bash
python main.py --help
```

## Run the Web UI Locally

```bash
uvicorn app.web.main:app --reload
```

Then open [http://127.0.0.1:8000/dashboard](http://127.0.0.1:8000/dashboard).

The web UI is a thin control panel over the existing pipeline. It reuses the current SQLAlchemy models, repositories, services, source connectors, parsers, and database instead of replacing the CLI.

## Cloud Deployment

This application supports deploying to a cloud platform (like Render, Railway, or Fly.io) and using a managed PostgreSQL database (e.g., Supabase).

### Environment Variables

When deploying to the cloud, configure the following environment variables:

- `APP_ENV`: Set to `production`
- `DATABASE_URL`: Set to your PostgreSQL connection string (e.g., `postgresql+psycopg2://postgres:YOUR_PASSWORD@db.supabase.co:5432/postgres`)
- `OPENAI_API_KEY`: Your OpenAI API key for LLM analysis

### Deployment using Docker

A `Dockerfile` is included to easily deploy the application. It automatically runs the FastAPI web UI bound to `0.0.0.0` and listens on the port specified by the `$PORT` environment variable (defaults to 8000).

**Render / Railway Setup:**
1. Connect your GitHub repository to your cloud provider.
2. Select "Docker" as the deployment method.
3. Set your environment variables (including the Supabase `DATABASE_URL`).
4. The platform will automatically build the image and start the server using:
   `uvicorn app.web.main:app --host 0.0.0.0 --port $PORT`
