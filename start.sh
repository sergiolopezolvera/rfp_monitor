#!/bin/bash
set -e

# Run migration if we're in production and have a postgres URL
if [ "$APP_ENV" = "production" ] && [[ "$DATABASE_URL" == postgres* ]]; then
    echo "Running database migration..."
    # Always append sslmode to URL if missing, Render pg instances require it
    if [[ "$DATABASE_URL" != *"sslmode"* ]]; then
        if [[ "$DATABASE_URL" == *"?"* ]]; then
            export DATABASE_URL="${DATABASE_URL}&sslmode=require"
        else
            export DATABASE_URL="${DATABASE_URL}?sslmode=require"
        fi
    fi
    python migrate_db.py
fi

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT:-8000}
