from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter()


def _allowed_roots() -> tuple[Path, ...]:
    return (
        settings.raw_dir.resolve(),
        settings.parsed_dir.resolve(),
        settings.export_dir.resolve(),
    )


def _is_allowed_path(file_path: Path) -> bool:
    resolved = file_path.resolve()
    return any(root == resolved or root in resolved.parents for root in _allowed_roots())


@router.get("/artifacts")
def read_artifact(path: str = Query(...)):
    file_path = Path(path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    if not _is_allowed_path(file_path):
        raise HTTPException(status_code=403, detail="Path is outside allowed data directories")
    return FileResponse(file_path)
