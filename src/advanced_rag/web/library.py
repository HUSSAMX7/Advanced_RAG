"""One local library owns training, cancellation, corpus mutation and recovery."""

import asyncio
import logging
import threading
from dataclasses import dataclass, field

from ..ingestion.documents import prepare_document
from ..retrieval import load_search_context
from ..storage import (
    TrainingCancelled,
    committed_file_counts,
    file_key,
    index_revision,
    read_index_nodes,
    remove_file_from_faiss,
    store_in_faiss,
)
from .registry import Registry

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


class Library:
    def __init__(self, settings, *, prepare=prepare_document, embed_model=None):
        self.settings = settings
        self.registry = Registry(settings.web_data_dir)
        self.prepare = prepare
        self.embed_model = embed_model
        self.jobs: dict[str, Job] = {}
        self.removals: set[str] = set()
        self.mutation_lock = asyncio.Lock()
        self.commit_lock = threading.RLock()
        self._revision = None
        self._context = None
        self._nodes = []

    def _sync(self):
        revision = index_revision(self.settings)
        if revision == self._revision:
            return
        self._nodes, _ = read_index_nodes(self.settings)
        counts = {}
        names = {}
        for node in self._nodes:
            key = file_key(node)
            counts[key] = counts.get(key, 0) + 1
            names[key] = str(node.metadata.get("source", node.metadata.get("paper_path", key)))
        rows = {row["id"]: row for row in self.registry.list()}
        for key, count in counts.items():
            if key not in rows:
                self.registry.add(names[key], 0, file_id=key, status="trained")
            self.registry.update(key, status="trained", stage=None, error=None, chunks=count)
        for key, row in rows.items():
            if row["status"] == "trained" and key not in counts:
                self.registry.update(key, status="untrained", chunks=0, stage=None)
        self._revision = revision
        self._context = None

    async def start(self):
        self.settings.faiss_persist_dir.mkdir(parents=True, exist_ok=True)
        self._sync()
        for row in self.registry.list():
            if row["intent"]:
                await self.remove(row["id"], delete=row["intent"] == "delete")
            elif row["status"] == "queued":
                self.train(row["id"])
            elif row["status"] in {"training", "cancelling"}:
                self.registry.update(
                    row["id"],
                    status="failed",
                    stage=None,
                    error="توقف التطبيق قبل اكتمال التدريب. يمكنك إعادة المحاولة.",
                )
        # Remove orphan uploads left by interrupted requests, retaining registered originals.
        originals = {row["original"] for row in self.registry.list() if row["original"]}
        for path in self.registry.uploads.iterdir():
            if path.name not in originals and path.is_file():
                path.unlink(missing_ok=True)

    async def close(self):
        for job in self.jobs.values():
            with self.commit_lock:
                job.cancel.set()
        await asyncio.gather(
            *(job.task for job in self.jobs.values() if job.task), return_exceptions=True
        )

    def list(self):
        self._sync()
        return [self.registry.public(row) for row in self.registry.list()]

    def train(self, file_id):
        row = self.registry.get(file_id)
        if row["intent"]:
            raise LibraryConflict("انتظر اكتمال العملية الحالية على الملف.")
        job = self.jobs.get(file_id)
        if row["status"] == "trained" or (job and job.task and not job.task.done()):
            return self.registry.public(row)
        if not row["original"]:
            raise LibraryConflict("الملف أُضيف من سطر الأوامر. أعد رفعه لتدريبه من المكتبة.")
        job = Job()
        self.jobs[file_id] = job
        self.registry.update(file_id, status="queued", stage=None, error=None)
        job.task = asyncio.create_task(self._train(file_id, job))
        return self.registry.public(self.registry.get(file_id))

    async def _train(self, file_id, job):
        acquired = False
        try:
            await cancellable(
                self.mutation_lock.acquire(),
                job.cancel,
                cancelled_result=lambda _: self.mutation_lock.release(),
            )
            acquired = True
            if job.cancel.is_set():
                raise TrainingCancelled()
            row = self.registry.get(file_id)
            original = row["original"]
            if original is None:
                raise ValueError("الملف الأصلي غير متوفر. أعد رفعه لتدريبه.")
            self.registry.update(file_id, status="training", stage="extracting")
            data = await asyncio.to_thread((self.registry.uploads / original).read_bytes)

            def progress(stage):
                self.registry.update(file_id, stage=stage)

            chunks = await cancellable(
                self.prepare(
                    {"resource_id": file_id, "file_name": row["name"], "data": data},
                    self.settings,
                    progress,
                ),
                job.cancel,
            )
            if job.cancel.is_set():
                raise TrainingCancelled()
            self.registry.update(file_id, stage="storing")
            await asyncio.to_thread(
                store_in_faiss,
                chunks,
                self.settings,
                embed_model=self.embed_model,
                cancelled=job.cancel.is_set,
                commit_lock=self.commit_lock,
            )
            self.registry.update(
                file_id, status="trained", stage=None, error=None, chunks=len(chunks)
            )
            self._sync()
        except TrainingCancelled:
            self.registry.update(file_id, status="cancelled", stage=None, error=None, chunks=0)
        except Exception as exc:
            logger.exception("Training failed for file %s", file_id)
            message = (
                str(exc)
                if isinstance(exc, ValueError)
                else "تعذر إكمال التدريب. تحقق من إعدادات الخدمات ثم أعد المحاولة."
            )
            self.registry.update(file_id, status="failed", stage=None, error=message)
        finally:
            if acquired:
                self.mutation_lock.release()

    async def cancel(self, file_id):
        row = self.registry.get(file_id)
        job = self.jobs.get(file_id)
        if not job or not job.task or job.task.done():
            return self.registry.public(row)
        with self.commit_lock:
            # A completed atomic commit wins over a cancellation arriving afterward.
            counts = committed_file_counts(self.settings)
            if file_id in counts:
                row = self.registry.update(
                    file_id, status="trained", stage=None, chunks=counts[file_id], error=None
                )
                return self.registry.public(row)
            job.cancel.set()
            self.registry.update(file_id, status="cancelling")
        await job.task
        return self.registry.public(self.registry.get(file_id))

    async def remove(self, file_id, *, delete=False):
        self.registry.get(file_id)
        if file_id in self.removals:
            raise LibraryConflict("هناك عملية حذف أو إزالة فهرسة جارية لهذا الملف.")
        self.removals.add(file_id)
        self.registry.update(file_id, intent="delete" if delete else "unindex")
        await self.cancel(file_id)
        try:
            async with self.mutation_lock:
                await asyncio.to_thread(remove_file_from_faiss, file_id, self.settings)
                if delete:
                    self.registry.delete(file_id)
                else:
                    self.registry.update(
                        file_id, status="untrained", stage=None, chunks=0, error=None, intent=None
                    )
                self._revision = None
                self._sync()
        except Exception:
            self.registry.update(
                file_id, error="تعذر إكمال العملية. أعد تشغيل التطبيق لإعادة المحاولة."
            )
            raise
        finally:
            self.removals.discard(file_id)
        return None if delete else self.registry.public(self.registry.get(file_id))

    def source(self, chunk_id):
        self._sync()
        for node in self._nodes:
            if node.node_id == chunk_id:
                row = self.registry.get(file_key(node))
                return {
                    "text": node.get_content(),
                    "metadata": node.metadata,
                    "file_id": row["id"],
                    "available": True,
                    "has_original": bool(row["original"]),
                }
        return {"text": None, "available": False, "has_original": False}

    @property
    def has_documents(self):
        return bool(self._nodes)

    def update_settings(self, settings):
        self.settings = settings
        self._context = None

    async def context(self):
        # Called only when the model chooses search; general answers never wait for a writer.
        async with self.mutation_lock:
            return await asyncio.to_thread(self._search_context)

    def _search_context(self):
        self._sync()
        if not self._nodes:
            return None
        if self._context is None:
            self._context = load_search_context(self.settings, embed_model=self.embed_model)
        return self._context
