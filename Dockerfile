FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APP_ENV=production
# Default port to 8000 if not set by the cloud provider
ENV PORT=8000

WORKDIR /app

# Install system dependencies required for psycopg2 and lxml
RUN apt-get update && apt-get install -y \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy application code
COPY . .

# Run the application using the start script
CMD ["./start.sh"]
