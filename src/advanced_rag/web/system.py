"""Small shared operational routes."""

from fastapi import APIRouter

from ..ingestion.documents import libreoffice_executable
from .dependencies import WorkspaceDependency

router = APIRouter()


@router.get("/api/health", tags=["system"])
async def health(workspace: WorkspaceDependency):
    settings = workspace.web_settings.current
    return {
        "status": "ok",
        "max_upload_bytes": settings.max_upload_bytes,
        "doc_available": libreoffice_executable(settings) is not None,
    }
