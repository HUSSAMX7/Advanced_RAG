"""Guest deadline/revocation records and guarded temporary workspace removal."""

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
        db.execute("""CREATE TABLE IF NOT EXISTS guests (
            id TEXT PRIMARY KEY, token_hash TEXT UNIQUE NOT NULL,
            renew_at REAL NOT NULL, expires_at REAL NOT NULL,
            close_at REAL, revoked INTEGER NOT NULL DEFAULT 0
        )""")


def insert(path, guest_id, token_hash, renew_at, expires_at):
    with connect(path) as db:
        db.execute(
            "INSERT INTO guests (id,token_hash,renew_at,expires_at) VALUES (?,?,?,?)",
            (guest_id, token_hash, renew_at, expires_at),
        )


def get(path, token_hash):
    with connect(path) as db:
        row = db.execute("SELECT * FROM guests WHERE token_hash=?", (token_hash,)).fetchone()
    return dict(row) if row is not None else None


def renew(path, guest_id, renew_at, expires_at):
    with connect(path) as db:
        db.execute(
            "UPDATE guests SET renew_at=?,expires_at=?,close_at=NULL WHERE id=?",
            (renew_at, expires_at, guest_id),
        )


def set_close_deadline(path, guest_id, deadline):
    with connect(path) as db:
        db.execute("UPDATE guests SET close_at=? WHERE id=?", (deadline, guest_id))


def revoke_token(path, token_hash):
    with connect(path) as db:
        row = db.execute("SELECT id FROM guests WHERE token_hash=?", (token_hash,)).fetchone()
        if row:
            db.execute("UPDATE guests SET revoked=1 WHERE id=?", (row["id"],))
    return row["id"] if row else None


def revoke_expired(path, now):
    with connect(path) as db:
        rows = db.execute(
            "SELECT id FROM guests WHERE revoked=1 OR expires_at<=? OR close_at<=?", (now, now)
        ).fetchall()
        for row in rows:
            db.execute("UPDATE guests SET revoked=1 WHERE id=?", (row["id"],))
    return [row["id"] for row in rows]


def remove(path, root, guest_id):
    if str(UUID(guest_id)) != guest_id:
        raise ValueError("Invalid guest identity")
    root = (root / "guests").resolve()
    target = (root / guest_id).resolve()
    if target.parent != root:
        raise ValueError("Guest path escaped its workspace")
    if target.exists():
        shutil.rmtree(target)
    with connect(path) as db:
        db.execute("DELETE FROM guests WHERE id=?", (guest_id,))
