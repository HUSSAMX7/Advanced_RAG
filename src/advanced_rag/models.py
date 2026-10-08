"""Plain dictionary inputs and outputs for PDF processing functions."""

from pathlib import Path
from typing import NotRequired, TypedDict
from uuid import NAMESPACE_URL, uuid5

PdfResource = TypedDict(
    "PdfResource",
    {
        "resource_id": str,
        "file_name": str,
        "data": bytes,
        "include_images": NotRequired[bool],
    },
)
FileStatus = TypedDict(
    "FileStatus",
    {
        "file_id": str,
        "file_name": str,
        "success": bool,
        "error": str | None,
    },
)


def resource_from_path(path: str | Path) -> PdfResource:
    source = Path(path).resolve()
    if source.suffix.lower() != ".pdf":
        raise ValueError(f"Only PDF files are supported: {source.name}")
    return {
        "resource_id": str(uuid5(NAMESPACE_URL, source.as_uri())),
        "file_name": source.name,
        "data": source.read_bytes(),
    }


def file_status(resource_id: str, file_name: str, *, error: str | None = None) -> FileStatus:
    return {
        "file_id": resource_id,
        "file_name": file_name,
        "success": False,
        "error": error,
    }
