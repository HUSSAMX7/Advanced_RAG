"""Assistant SQLite records and guarded workspace removal."""

import shutil
import sqlite3
from contextlib import closing, contextmanager
from uuid import UUID


@contextmanager
def connect(path):
    with closing(sqlite3.connect(path)) as db, db:
        db.row_factory = sqlite3.Row
        yield db


def initialize(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with connect(path) as db:
        db.execute("""CREATE TABLE IF NOT EXISTS assistants (
            id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
            instructions TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            deleting INTEGER NOT NULL DEFAULT 0
        )""")


def get(path, assistant_id, *, include_deleting=False):
    try:
        if str(UUID(assistant_id)) != assistant_id:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise FileNotFoundError("المساعد غير موجود.") from None
    with connect(path) as db:
        row = db.execute("SELECT * FROM assistants WHERE id=?", (assistant_id,)).fetchone()
    if row is None or (row["deleting"] and not include_deleting):
        raise FileNotFoundError("المساعد غير موجود.")
    return dict(row)


def list_rows(path, *, include_deleting=False):
    query = "SELECT * FROM assistants"
    if not include_deleting:
        query += " WHERE deleting=0 ORDER BY created_at,rowid"
    with connect(path) as db:
        return [dict(row) for row in db.execute(query)]


def insert(path, assistant_id, fields):
    with connect(path) as db:
        db.execute(
            "INSERT INTO assistants (id,name,description,instructions) VALUES (?,?,?,?)",
            (assistant_id, fields.name, fields.description, fields.instructions),
        )


def update(path, assistant_id, fields):
    with connect(path) as db:
        db.execute(
            "UPDATE assistants SET name=?,description=?,instructions=? WHERE id=?",
            (fields.name, fields.description, fields.instructions, assistant_id),
        )


def mark_deleting(path, assistant_id):
    with connect(path) as db:
        db.execute("UPDATE assistants SET deleting=1 WHERE id=?", (assistant_id,))


def remove(path, root, assistant_id):
    get(path, assistant_id, include_deleting=True)
    root = root.resolve()
    target = (root / assistant_id).resolve()
    if target.parent != root:
        raise ValueError("مسار المساعد غير صالح.")
    if target.exists():
        shutil.rmtree(target)
    with connect(path) as db:
        db.execute("DELETE FROM assistants WHERE id=?", (assistant_id,))
