"""Assistant operations; shared lifecycle data is passed explicitly."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..files import object_storage, processing
from ..files.processing import LibraryConflict, LibraryState
from . import repository


@dataclass
class AssistantState:
    """One owner's live libraries, deletion state and shared operation lock."""

    settings: Any
    prepare: Any
    embed_model: Any
    mutation_lock: asyncio.Lock
    root: Path
    path: Path
    libraries: dict[str, LibraryState] = field(default_factory=dict)
    inflight: dict[str, int] = field(default_factory=dict)
    deleting: set[str] = field(default_factory=set)


def initialize(settings, *, prepare, embed_model, mutation_lock):
    root = settings.web_data_dir / "assistants"
    root.mkdir(parents=True, exist_ok=True)
    path = settings.web_data_dir / "assistants.sqlite3"
    repository.initialize(path)
    return AssistantState(settings, prepare, embed_model, mutation_lock, root, path)


def scoped_settings(state, row):
    directory = state.root / row["id"]
    return state.settings.model_copy(
        update={
            "web_data_dir": directory / "library",
            "faiss_persist_dir": directory / "index",
            "chat_sessions_dir": directory / "conversations",
            "assistant_instructions": row["instructions"],
            "document_storage_prefix": state.settings.document_storage_prefix
            + "/assistants/"
            + row["id"],
        }
    )


def get_library(state, assistant_id):
    row = repository.get(state.path, assistant_id)
    if assistant_id not in state.libraries:
        library = processing.create_library(
            scoped_settings(state, row), prepare=state.prepare, embed_model=state.embed_model
        )
        library.mutation_lock = state.mutation_lock
        state.libraries[assistant_id] = library
    return state.libraries[assistant_id]


def public(state, row):
    library = get_library(state, row["id"])
    files = processing.list_files(library)
    return {
        key: row[key] for key in ("id", "name", "description", "instructions", "created_at")
    } | {
        "files": len(files),
        "trained": sum(file["status"] == "trained" for file in files),
        "conversations": sum(1 for _ in library.settings.chat_sessions_dir.glob("*.json")),
    }


def list_assistants(state):
    return [public(state, row) for row in repository.list_rows(state.path)]


def get_assistant(state, assistant_id):
    return public(state, repository.get(state.path, assistant_id))


async def create_assistant(state, fields):
    assistant_id = str(uuid4())
    repository.insert(state.path, assistant_id, fields)
    await processing.start(get_library(state, assistant_id))
    return get_assistant(state, assistant_id)


def update_assistant(state, assistant_id, fields):
    repository.get(state.path, assistant_id)
    if state.inflight.get(assistant_id):
        raise LibraryConflict("انتظر اكتمال العملية الحالية قبل تعديل المساعد.")
    repository.update(state.path, assistant_id, fields)
    row = repository.get(state.path, assistant_id)
    processing.update_settings(get_library(state, assistant_id), scoped_settings(state, row))
    return public(state, row)


def begin_delete(state, assistant_id):
    repository.get(state.path, assistant_id)
    if state.inflight.get(assistant_id):
        raise LibraryConflict("انتظر اكتمال الإجابة أو رفع الملف قبل حذف المساعد.")
    repository.mark_deleting(state.path, assistant_id)
    state.deleting.add(assistant_id)


async def finish_delete(state, assistant_id):
    library = state.libraries.get(assistant_id)
    if library is not None:
        await processing.close(library)
    await asyncio.to_thread(
        object_storage.delete_workspace,
        scoped_settings(state, repository.get(state.path, assistant_id, include_deleting=True)),
    )
    await asyncio.to_thread(repository.remove, state.path, state.root, assistant_id)
    state.libraries.pop(assistant_id, None)
    state.inflight.pop(assistant_id, None)
    state.deleting.discard(assistant_id)


async def delete_assistant(workspace, assistant_id):
    state = workspace.assistants
    selected = get_library(state, assistant_id)
    begin_delete(state, assistant_id)
    tasks = [
        task
        for (directory, _), task in workspace.title_tasks.items()
        if directory == selected.settings.chat_sessions_dir
    ]
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await finish_delete(state, assistant_id)


async def start(state):
    for row in repository.list_rows(state.path, include_deleting=True):
        if row["deleting"]:
            state.deleting.add(row["id"])
            await finish_delete(state, row["id"])
        else:
            await processing.start(get_library(state, row["id"]))


async def close(state):
    await asyncio.gather(*(processing.close(library) for library in state.libraries.values()))


def update_settings(state, settings):
    state.settings = settings
    for assistant_id, library in state.libraries.items():
        if assistant_id not in state.deleting:
            row = repository.get(state.path, assistant_id, include_deleting=True)
            if not row["deleting"]:
                processing.update_settings(library, scoped_settings(state, row))
