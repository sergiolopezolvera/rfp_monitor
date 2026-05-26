import os
import sys
from urllib.parse import urlparse

from sqlalchemy import create_engine, text

def migrate():
    pg_url = os.environ.get("DATABASE_URL")
    if not pg_url:
        print("DATABASE_URL not set. Skipping PostgreSQL ALTER TABLE.")
        # But we should also consider sqlite if they are using that
        sqlite_url = "sqlite:///rfp_monitor.db"
        sqlite_engine = create_engine(sqlite_url)
        # SQLite doesn't strictly enforce string length for VARCHAR, but good to know
        print(f"Checking SQLite at {sqlite_url}...")
        try:
            with sqlite_engine.begin() as conn:
                # SQLite ALTER COLUMN TYPE is tricky, but SQLite ignores VARCHAR lengths anyway so it's not the cause of the error.
                pass
            print("SQLite doesn't enforce VARCHAR length, no ALTER needed.")
        except Exception as e:
            print(f"Error accessing SQLite: {e}")
        return

    print(f"Altering category column to TEXT in {pg_url}...")

    connect_args = {}
    parsed_url = urlparse(pg_url)
    if parsed_url.hostname and ("render.com" in parsed_url.hostname or "supabase" in parsed_url.hostname):
        connect_args["sslmode"] = "require"

    pg_engine = create_engine(pg_url, connect_args=connect_args)

    try:
        with pg_engine.begin() as conn:
            conn.execute(text("ALTER TABLE opportunities ALTER COLUMN category TYPE TEXT;"))
            print("Successfully altered category column to TEXT in PostgreSQL.")
    except Exception as e:
        print(f"Error executing ALTER TABLE: {e}")

if __name__ == "__main__":
    migrate()
