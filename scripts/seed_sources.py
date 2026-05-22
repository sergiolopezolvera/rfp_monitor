from app.db import SessionLocal
from app.logger import logger
from app.services.source_service import seed_default_sources


def main() -> None:
    logger.info("Seeding default sources...")

    with SessionLocal() as db:
        results = seed_default_sources(db)

    for source_name, created in results:
        status = "created" if created else "already existed"
        print(f"{source_name}: {status}")

    logger.info("Default sources seed completed.")


if __name__ == "__main__":
    main()