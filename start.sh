#!/bin/bash
set -e

# Start the application
echo "Starting uvicorn..."
exec uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT:-8000}
