"""One local library owns training, cancellation, corpus mutation and recovery."""

import asyncio
import logging
import threading
from dataclasses import dataclass, field
from typing import Any

from ...ingestion.documents import prepare_document
from ...retrieval import load_search_context
from ...storage import (
    TrainingCancelled,
    committed_file_counts,
    file_key,
    index_revision,
    read_index_nodes,
    remove_file_from_faiss,
    store_in_faiss,
)
from ...visuals import evidence_metadata, evidence_text, image_path, prune_images
from . import repository
from .schemas import public

logger = logging.getLogger(__name__)
BUSY = {"queued", "training", "cancelling"}


class LibraryConflict(Exception):
    pass


@dataclass
class Job:
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task | None = None


async def cancellable(awaitable, event: asyncio.Event, cancelled_result=None):
    work = asyncio.ensure_future(awaitable)
    stop = asyncio.create_task(event.wait())
    try:
        await asyncio.wait({work, stop}, return_when=asyncio.FIRST_COMPLETED)
        if event.is_set():
            work.cancel()
            await asyncio.gather(work, return_exceptions=True)
            if cancelled_result and not work.cancelled() and work.exception() is None:
                cancelled_result(work.result())
            raise TrainingCancelled()
        return await work
    finally:
        stop.cancel()
        await asyncio.gather(stop, return_exceptions=True)


@dataclass
class LibraryState:
    """One library's index cache, task registry and publication/cancellation locks."""

    settings: Any
    registry: Any
    prepare: Any
    embed_model: Any = None
    jobs: dict[str, Job] = field(default_factory=dict)
    removals: set[str] = field(default_factory=set)
    mutation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    commit_lock: Any = field(default_factory=threading.RLock)
    _revision: Any = None
    _context: Any = None
    _nodes: list = field(default_factory=list)


def create_library(settings, *, prepare=prepare_document, embed_model=None):
    return LibraryState(
        settings, repository.initialize(settings.web_data_dir), prepare, embed_model
    )


def _sync(state):
    # Windows may reject a read concurrent with the atomic pointer replacement.
    # Hold this only for the pointer read, never while acquiring the index lock.
    with state.commit_lock:
        revision = index_revision(state.settings)
    if revision == state._revision:
        return
    state._nodes, _ = read_index_nodes(state.settings)
    counts = {}
    names = {}
    for node in state._nodes:
        key = file_key(node)
        counts[key] = counts.get(key, 0) + 1
        names[key] = str(node.metadata.get("source", node.metadata.get("paper_path", key)))
    rows = {
        row["id"]: row
        for row in repository.list_files(
            state.registry,
        )
    }
    for key, count in counts.items():
        if key not in rows:
            repository.add(state.registry, names[key], 0, file_id=key, status="trained")
        repository.update(
            state.registry, key, status="trained", stage=None, error=None, chunks=count
        )
    for key, row in rows.items():
        if row["status"] == "trained" and key not in counts:
            repository.update(state.registry, key, status="untrained", chunks=0, stage=None)
    state._revision = revision
    state._context = None


async def start(state):
    state.settings.faiss_persist_dir.mkdir(parents=True, exist_ok=True)
    _sync(state)
    # Prune before restarting queued jobs: their staged images are not indexed yet.
    await asyncio.to_thread(_prune_images, state)
    for row in repository.list_files(
        state.registry,
    ):
        if row["intent"]:
            await remove(state, row["id"], delete=row["intent"] == "delete")
        elif row["status"] == "queued":
            train(state, row["id"])
        elif row["status"] in {"training", "cancelling"}:
            repository.update(
                state.registry,
                row["id"],
                status="failed",
                stage=None,
                error="توقف التطبيق قبل اكتمال التدريب. يمكنك إعادة المحاولة.",
            )
    # Remove orphan uploads left by interrupted requests, retaining registered originals.
    originals = {
        row["original"]
        for row in repository.list_files(
            state.registry,
        )
        if row["original"]
    }
    for path in repository.uploads(state.registry).iterdir():
        if path.name not in originals and path.is_file():
            path.unlink(missing_ok=True)


async def close(state):
    for job in state.jobs.values():
        with state.commit_lock:
            job.cancel.set()
    await asyncio.gather(
        *(job.task for job in state.jobs.values() if job.task), return_exceptions=True
    )


def list_files(state):
    _sync(state)
    warnings = {
        file_key(node): node.metadata["visual_warning"]
        for node in state._nodes
        if node.metadata.get("visual_warning")
    }
    return [
        {**public(row), "warning": warnings.get(row["id"])}
        for row in repository.list_files(
            state.registry,
        )
    ]


def _prune_images(state):
    nodes, _ = read_index_nodes(state.settings)
    prune_images(state.settings, nodes)


def train(state, file_id):
    row = repository.get(state.registry, file_id)
    if row["intent"]:
        raise LibraryConflict("انتظر اكتمال العملية الحالية على الملف.")
    job = state.jobs.get(file_id)
    if row["status"] == "trained" or (job and job.task and not job.task.done()):
        return public(row)
    if not row["original"]:
        raise LibraryConflict("الملف أُضيف من سطر الأوامر. أعد رفعه لتدريبه من المكتبة.")
    job = Job()
    state.jobs[file_id] = job
    repository.update(state.registry, file_id, status="queued", stage=None, error=None)
    job.task = asyncio.create_task(_train(state, file_id, job))
    return public(repository.get(state.registry, file_id))


async def _train(state, file_id, job):
    acquired = False
    try:
        await cancellable(
            state.mutation_lock.acquire(),
            job.cancel,
            cancelled_result=lambda _: state.mutation_lock.release(),
        )
        acquired = True
        if job.cancel.is_set():
            raise TrainingCancelled()
        row = repository.get(state.registry, file_id)
        original = row["original"]
        if original is None:
            raise ValueError("الملف الأصلي غير متوفر. أعد رفعه لتدريبه.")
        repository.update(state.registry, file_id, status="training", stage="extracting")
        data = await asyncio.to_thread((repository.uploads(state.registry) / original).read_bytes)

        def progress(stage):
            repository.update(state.registry, file_id, stage=stage)

        chunks = await cancellable(
            state.prepare(
                {
                    "resource_id": file_id,
                    "file_name": row["name"],
                    "data": data,
                    "include_images": bool(row["image_support"]),
                },
                state.settings,
                progress,
            ),
            job.cancel,
        )
        if job.cancel.is_set():
            raise TrainingCancelled()
        repository.update(state.registry, file_id, stage="storing")
        await asyncio.to_thread(
            store_in_faiss,
            chunks,
            state.settings,
            embed_model=state.embed_model,
            cancelled=job.cancel.is_set,
            commit_lock=state.commit_lock,
        )
        repository.update(
            state.registry, file_id, status="trained", stage=None, error=None, chunks=len(chunks)
        )
        _sync(state)
    except TrainingCancelled:
        repository.update(
            state.registry, file_id, status="cancelled", stage=None, error=None, chunks=0
        )
    except Exception as exc:
        logger.exception("Training failed for file %s", file_id)
        message = (
            str(exc)
            if isinstance(exc, ValueError)
            else "تعذر إكمال التدريب. تحقق من إعدادات الخدمات ثم أعد المحاولة."
        )
        repository.update(state.registry, file_id, status="failed", stage=None, error=message)
    finally:
        if acquired:
            try:
                await asyncio.to_thread(_prune_images, state)
            finally:
                state.mutation_lock.release()


async def cancel(state, file_id):
    row = repository.get(state.registry, file_id)
    job = state.jobs.get(file_id)
    if not job or not job.task or job.task.done():
        return public(row)
    with state.commit_lock:
        # A completed atomic commit wins over a cancellation arriving afterward.
        counts = committed_file_counts(state.settings)
        if file_id in counts:
            row = repository.update(
                state.registry,
                file_id,
                status="trained",
                stage=None,
                chunks=counts[file_id],
                error=None,
            )
            return public(row)
        job.cancel.set()
        repository.update(state.registry, file_id, status="cancelling")
    await job.task
    return public(repository.get(state.registry, file_id))


async def remove(state, file_id, *, delete=False):
    repository.get(state.registry, file_id)
    if file_id in state.removals:
        raise LibraryConflict("هناك عملية حذف أو إزالة فهرسة جارية لهذا الملف.")
    state.removals.add(file_id)
    repository.update(state.registry, file_id, intent="delete" if delete else "unindex")
    await cancel(state, file_id)
    try:
        async with state.mutation_lock:
            await asyncio.to_thread(remove_file_from_faiss, file_id, state.settings)
            await asyncio.to_thread(_prune_images, state)
            if delete:
                repository.delete(state.registry, file_id)
            else:
                repository.update(
                    state.registry,
                    file_id,
                    status="untrained",
                    stage=None,
                    chunks=0,
                    error=None,
                    intent=None,
                )
            state._revision = None
            _sync(state)
    except Exception:
        repository.update(
            state.registry, file_id, error="تعذر إكمال العملية. أعد تشغيل التطبيق لإعادة المحاولة."
        )
        raise
    finally:
        state.removals.discard(file_id)
    return None if delete else public(repository.get(state.registry, file_id))


def source(state, chunk_id):
    _sync(state)
    for node in state._nodes:
        if node.node_id == chunk_id:
            row = repository.get(state.registry, file_key(node))
            return {
                "text": evidence_text(node),
                "metadata": evidence_metadata(node.metadata),
                "file_id": row["id"],
                "available": True,
                "has_original": bool(row["original"]),
                "images": [
                    {**image, "url": f"/api/sources/{chunk_id}/images/{image['id']}"}
                    for image in node.metadata.get("images", [])
                    if image_path(state.settings, image["id"]).is_file()
                ],
            }
    return {"text": None, "available": False, "has_original": False}


def image(state, chunk_id, image_id):
    detail = source(state, chunk_id)
    if not detail["available"] or not any(
        image["id"] == image_id for image in detail.get("images", [])
    ):
        raise FileNotFoundError("الصورة لم تعد متاحة ضمن هذا المصدر.")
    return image_path(state.settings, image_id)


def has_documents(state):
    return bool(state._nodes)


def update_settings(state, settings):
    state.settings = settings
    state._context = None


async def context(state):
    # Called only when the model chooses search; general answers never wait for a writer.
    async with state.mutation_lock:
        return await asyncio.to_thread(_search_context, state)


def _search_context(state):
    _sync(state)
    if not state._nodes:
        return None
    if state._context is None:
        state._context = load_search_context(state.settings, embed_model=state.embed_model)
    return state._context
