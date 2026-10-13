"""Document lifecycle records and public projections."""

import re
from collections.abc import Mapping
from typing import Literal, TypedDict, cast, get_args

LibraryStatus = Literal[
    "untrained", "queued", "training", "cancelling", "trained", "failed", "cancelled"
]
TrainingStage = Literal["extracting", "chunking", "storing", "preparing_ocr", "describing_images"]
FileIntent = Literal["delete", "unindex"]


class FileRecord(TypedDict):
    id: str
    name: str
    size: int
    type: str
    status: LibraryStatus
    stage: str | None
    error: str | None
    chunks: int
    created_at: str
    updated_at: str


class StoredFile(FileRecord):
    original: str | None
    intent: FileIntent | None
    image_support: int


class PublicFile(FileRecord):
    has_original: bool


class FileChanges(TypedDict, total=False):
    status: LibraryStatus
    stage: str | None
    error: str | None
    chunks: int
    intent: FileIntent | None


def validate_lifecycle(values: Mapping[str, object]) -> None:
    for key, allowed in (
        ("status", get_args(LibraryStatus)),
        ("intent", (*get_args(FileIntent), None)),
    ):
        if key in values and values[key] not in allowed:
            raise ValueError(f"Invalid persisted file {key}")
    stage = values.get("stage")
    if stage is not None and stage not in get_args(TrainingStage):
        match = (
            re.fullmatch(r"ocr_page:([1-9][0-9]*):([1-9][0-9]*)", stage)
            if isinstance(stage, str)
            else None
        )
        if not match or int(match[1]) > int(match[2]):
            raise ValueError("Invalid persisted file stage")


def public(row: StoredFile) -> PublicFile:
    return cast(
        PublicFile,
        {
            key: value
            for key, value in row.items()
            if key not in {"original", "intent", "image_support"}
        }
        | {
            "has_original": bool(row["original"]),
        },
    )
