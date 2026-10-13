"""Named, durable workspaces with independent libraries and conversation stores."""

import asyncio
import shutil
import sqlite3
from contextlib import closing
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .library import Library, LibraryConflict


class AssistantFields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    instructions: str = Field(default="", max_length=6000)

    @field_validator("name", "description", "instructions")
    @classmethod
    def trim(cls, value, info):
        value = value.strip()
        if info.field_name == "name" and not value:
            raise ValueError("اكتب اسم المساعد.")
        return value


class Assistants:
    def __init__(self, settings, *, prepare, embed_model, mutation_lock):
        self.settings = settings
        self.prepare = prepare
        self.embed_model = embed_model
        self.mutation_lock = mutation_lock
        self.root = settings.web_data_dir / "assistants"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = settings.web_data_dir / "assistants.sqlite3"
        self.libraries: dict[str, Library] = {}
        self.inflight: dict[str, int] = {}
        self.deleting: set[str] = set()
        with closing(self._db()) as db, db:
            db.execute("""CREATE TABLE IF NOT EXISTS assistants (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL,
                instructions TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                deleting INTEGER NOT NULL DEFAULT 0
            )""")

    def _db(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def _row(self, assistant_id, *, include_deleting=False):
        try:
            if str(UUID(assistant_id)) != assistant_id:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            raise FileNotFoundError("المساعد غير موجود.") from None
        with closing(self._db()) as db:
            row = db.execute("SELECT * FROM assistants WHERE id = ?", (assistant_id,)).fetchone()
        if row is None or (row["deleting"] and not include_deleting):
            raise FileNotFoundError("المساعد غير موجود.")
        return dict(row)

    def scoped_settings(self, row):
        directory = self.root / row["id"]
        return self.settings.model_copy(
            update={
                "web_data_dir": directory / "library",
                "faiss_persist_dir": directory / "index",
                "chat_sessions_dir": directory / "conversations",
                "assistant_instructions": row["instructions"],
            }
        )

    def library(self, assistant_id):
        row = self._row(assistant_id)
        if assistant_id not in self.libraries:
            library = Library(
                self.scoped_settings(row), prepare=self.prepare, embed_model=self.embed_model
            )
            # OCR, embedding writes and reranking share the local machine's resources.
            library.mutation_lock = self.mutation_lock
            self.libraries[assistant_id] = library
        return self.libraries[assistant_id]

    def public(self, row):
        library = self.library(row["id"])
        files = library.list()
        return {
            key: row[key] for key in ("id", "name", "description", "instructions", "created_at")
        } | {
            "files": len(files),
            "trained": sum(file["status"] == "trained" for file in files),
            "conversations": sum(1 for _ in library.settings.chat_sessions_dir.glob("*.json")),
        }

    def list(self):
        with closing(self._db()) as db:
            rows = db.execute(
                "SELECT * FROM assistants WHERE deleting = 0 ORDER BY created_at, rowid"
            ).fetchall()
        return [self.public(dict(row)) for row in rows]

    def get(self, assistant_id):
        return self.public(self._row(assistant_id))

    async def create(self, fields):
        assistant_id = str(uuid4())
        with closing(self._db()) as db, db:
            db.execute(
                "INSERT INTO assistants (id, name, description, instructions) VALUES (?, ?, ?, ?)",
                (assistant_id, fields.name, fields.description, fields.instructions),
            )
        await self.library(assistant_id).start()
        return self.public(self._row(assistant_id))

    def update(self, assistant_id, fields):
        self._row(assistant_id)
        if self.inflight.get(assistant_id):
            raise LibraryConflict("انتظر اكتمال العملية الحالية قبل تعديل المساعد.")
        with closing(self._db()) as db, db:
            db.execute(
                "UPDATE assistants SET name = ?, description = ?, instructions = ? WHERE id = ?",
                (fields.name, fields.description, fields.instructions, assistant_id),
            )
        row = self._row(assistant_id)
        self.library(assistant_id).update_settings(self.scoped_settings(row))
        return self.public(row)

    def begin_delete(self, assistant_id):
        self._row(assistant_id)
        if self.inflight.get(assistant_id):
            raise LibraryConflict("انتظر اكتمال الإجابة أو رفع الملف قبل حذف المساعد.")
        with closing(self._db()) as db, db:
            db.execute("UPDATE assistants SET deleting = 1 WHERE id = ?", (assistant_id,))
        self.deleting.add(assistant_id)

    def _remove_directory(self, assistant_id):
        # Validate the persisted identity and resolved target before recursive deletion.
        self._row(assistant_id, include_deleting=True)
        root = self.root.resolve()
        directory = (root / assistant_id).resolve()
        if directory.parent != root:
            raise ValueError("مسار المساعد غير صالح.")
        if directory.exists():
            shutil.rmtree(directory)
        with closing(self._db()) as db, db:
            db.execute("DELETE FROM assistants WHERE id = ?", (assistant_id,))

    async def finish_delete(self, assistant_id):
        library = self.libraries.get(assistant_id)
        if library is not None:
            await library.close()
        await asyncio.to_thread(self._remove_directory, assistant_id)
        self.libraries.pop(assistant_id, None)
        self.inflight.pop(assistant_id, None)
        self.deleting.discard(assistant_id)

    async def start(self):
        with closing(self._db()) as db:
            rows = db.execute("SELECT * FROM assistants").fetchall()
        for row in rows:
            if row["deleting"]:
                self.deleting.add(row["id"])
                await self.finish_delete(row["id"])
            else:
                await self.library(row["id"]).start()

    async def close(self):
        await asyncio.gather(*(library.close() for library in self.libraries.values()))

    def update_settings(self, settings):
        self.settings = settings
        for assistant_id, library in self.libraries.items():
            if assistant_id in self.deleting:
                continue
            row = self._row(assistant_id, include_deleting=True)
            if not row["deleting"]:
                library.update_settings(self.scoped_settings(row))
