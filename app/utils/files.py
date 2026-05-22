from pathlib import Path

from app.config import settings


def ensure_parent_dir(path: Path) -> None:
    """Create parent directory if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def write_text_file(path: Path, content: str) -> None:
    """Write UTF-8 text content to disk."""
    ensure_parent_dir(path)
    path.write_text(content, encoding="utf-8")


def build_raw_html_path(source_name: str, record_id: str) -> Path:
    """Build a consistent path for raw HTML storage."""
    safe_record_id = record_id.replace("/", "_").replace(":", "_")
    return settings.raw_dir / source_name / f"{safe_record_id}.html"


def build_raw_text_path(source_name: str, record_id: str) -> Path:
    """Build a consistent path for parsed raw text storage."""
    safe_record_id = record_id.replace("/", "_").replace(":", "_")
    return settings.parsed_dir / source_name / f"{safe_record_id}.txt"