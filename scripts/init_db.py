from app.db import Base, engine
from app.logger import logger
import app.models  # noqa: F401


def main() -> None:
    logger.info("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    logger.info("Database tables created successfully.")
    print("Database initialized successfully.")


if __name__ == "__main__":
    main()