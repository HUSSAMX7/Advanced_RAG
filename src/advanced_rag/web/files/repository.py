"""SQLite file records; original bytes and vector indexes remain separate."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Unpack, cast
from uuid import uuid4

from .schemas import FileChanges, LibraryStatus, StoredFile, validate_lifecycle


def uploads(directory: Path) -> Path:
    return directory / "uploads"


def initialize(directory: Path) -> Path:
    uploads(directory).mkdir(parents=True, exist_ok=True)
    with connect(directory) as connection:
        connection.execute("""CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, size INTEGER NOT NULL,
            type TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'untrained',
            stage TEXT, error TEXT, original TEXT, intent TEXT,
            chunks INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        )""")
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(files)")}
        if "image_support" not in columns:
            connection.execute(
                "ALTER TABLE files ADD COLUMN image_support INTEGER NOT NULL DEFAULT 0"
            )
    return directory


@contextmanager
def connect(directory: Path) -> Generator[sqlite3.Connection]:
    connection = sqlite3.connect(directory / "library.sqlite3")
    connection.row_factory = sqlite3.Row
    try:
        with connection:
            yield connection
    finally:
        connection.close()


def add(
    directory,
    name: str,
    size: int,
    *,
    file_id: str | None = None,
    original: str | None = None,
    status: LibraryStatus = "untrained",
    image_support: bool = False,
) -> StoredFile:
    validate_lifecycle({"status": status})
    file_id = file_id or str(uuid4())
    now = timestamp()
    with connect(directory) as connection:
        connection.execute(
            "INSERT INTO files (id,name,size,type,original,status,created_at,updated_at,image_support) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                file_id,
                name,
                size,
                Path(name).suffix.lower().lstrip("."),
                original,
                status,
                now,
                now,
                int(image_support),
            ),
        )
    return get(directory, file_id)


def get(directory, file_id: str) -> StoredFile:
    with connect(directory) as connection:
        row = connection.execute("SELECT * FROM files WHERE id=?", (file_id,)).fetchone()
    if row is None:
        raise FileNotFoundError("الملف غير موجود في المكتبة.")
    return record(row)


def list_files(directory) -> list[StoredFile]:
    with connect(directory) as connection:
        return [
            record(row)
            for row in connection.execute("SELECT * FROM files ORDER BY created_at DESC")
        ]


def update(directory, file_id: str, **changes: Unpack[FileChanges]) -> StoredFile:
    allowed = {"status", "stage", "error", "chunks", "intent"}
    if not changes or not set(changes).issubset(allowed):
        raise ValueError("Invalid file update")
    validate_lifecycle(changes)
    updates: dict[str, object] = dict(changes)
    updates["updated_at"] = timestamp()
    assignments = ",".join(f"{key}=?" for key in updates)
    with connect(directory) as connection:
        connection.execute(
            f"UPDATE files SET {assignments} WHERE id=?", (*updates.values(), file_id)
        )
    return get(directory, file_id)


def delete(directory, file_id: str):
    row = get(directory, file_id)
    if row["original"]:
        (uploads(directory) / row["original"]).unlink(missing_ok=True)
    with connect(directory) as connection:
        connection.execute("DELETE FROM files WHERE id=?", (file_id,))


def record(row: sqlite3.Row) -> StoredFile:
    values = dict(row)
    validate_lifecycle(values)
    return cast(StoredFile, values)


def timestamp() -> str:
    return datetime.now(UTC).isoformat()
