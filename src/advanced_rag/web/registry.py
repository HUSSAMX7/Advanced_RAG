"""Durable library records; file bytes and vectors live outside SQLite."""

import re
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, Unpack, cast, get_args
from uuid import uuid4

LibraryStatus = Literal[
    "untrained", "queued", "training", "cancelling", "trained", "failed", "cancelled"
]
TrainingStage = Literal["extracting", "chunking", "storing", "preparing_ocr"]
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


def record(row: sqlite3.Row) -> StoredFile:
    values = dict(row)
    validate_lifecycle(values)
    return cast(StoredFile, values)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()


class Registry:
    def __init__(self, directory: Path):
        self.directory = directory
        self.uploads = directory / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.path = directory / "library.sqlite3"
        with self.connect() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS files (
                    id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
                    type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'untrained',
                    stage TEXT, error TEXT, original TEXT, intent TEXT,
                    chunks INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                )
            """)

    def connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def add(
        self,
        name: str,
        size: int,
        *,
        file_id: str | None = None,
        original: str | None = None,
        status: LibraryStatus = "untrained",
    ) -> StoredFile:
        validate_lifecycle({"status": status})
        file_id = file_id or str(uuid4())
        now = timestamp()
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO files (id,name,size,type,original,status,created_at,updated_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    file_id,
                    name,
                    size,
                    Path(name).suffix.lower().lstrip("."),
                    original,
                    status,
                    now,
                    now,
                ),
            )
        return self.get(file_id)

    def get(self, file_id: str) -> StoredFile:
        with self.connect() as connection:
            row = connection.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("الملف غير موجود في المكتبة.")
        return record(row)

    def list(self) -> list[StoredFile]:
        with self.connect() as connection:
            return [
                record(row)
                for row in connection.execute("SELECT * FROM files ORDER BY created_at DESC")
            ]

    def update(self, file_id: str, **changes: Unpack[FileChanges]) -> StoredFile:
        allowed = {"status", "stage", "error", "chunks", "intent"}
        if not changes or not set(changes).issubset(allowed):
            raise ValueError("Invalid file update")
        validate_lifecycle(changes)
        updates: dict[str, object] = dict(changes)
        updates["updated_at"] = timestamp()
        assignments = ",".join(f"{key}=?" for key in updates)
        with self.connect() as connection:
            connection.execute(
                f"UPDATE files SET {assignments} WHERE id=?", (*updates.values(), file_id)
            )
        return self.get(file_id)

    def delete(self, file_id: str):
        row = self.get(file_id)
        if row["original"]:
            (self.uploads / row["original"]).unlink(missing_ok=True)
        with self.connect() as connection:
            connection.execute("DELETE FROM files WHERE id=?", (file_id,))

    @staticmethod
    def public(row: StoredFile) -> PublicFile:
        return cast(
            PublicFile,
            {key: value for key, value in row.items() if key not in {"original", "intent"}}
            | {
                "has_original": bool(row["original"]),
            },
        )
