import logging
from pathlib import Path

from app.config import settings


def setup_logger() -> logging.Logger:
    """Configure and return the application logger."""
    settings.ensure_directories()

    logger = logging.getLogger("rfp_monitor")
    logger.setLevel(getattr(logging, settings.log_level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)

    log_file = Path(settings.log_dir) / "app.log"
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setFormatter(formatter)

    logger.addHandler(stream_handler)
    logger.addHandler(file_handler)
    logger.propagate = False

    return logger


logger = setup_logger()