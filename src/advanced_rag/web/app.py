"""FastAPI host for the local library and the built React client."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, FastAPI, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, Field

from ..agent import ask_agent
from ..agent.memory import MemoryContextError
from ..agent.sessions import load_session, save_session
from ..agent.titles import fallback_title, generate_title
from ..config import Settings, require_openai_key
from ..ingestion.documents import libreoffice_executable, prepare_document
from ..retrieval.reranking import RerankingError
from .assistants import AssistantFields, Assistants
from .library import Library, LibraryConflict
from .settings import SettingsPatch, WebSettings

logger = logging.getLogger(__name__)
SUPPORTED = {".pdf", ".doc", ".docx", ".txt"}


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=12000)


def create_app(settings=None, *, prepare=prepare_document, embed_model=None, answer=ask_agent):
    web_settings = WebSettings(settings or Settings())
    runtime_settings: Settings = web_settings.current
    library = Library(runtime_settings, prepare=prepare, embed_model=embed_model)
    assistants = Assistants(
        runtime_settings,
        prepare=prepare,
        embed_model=embed_model,
        mutation_lock=library.mutation_lock,
    )
    workspace = APIRouter(prefix="/api/assistants/{assistant_id}")
    session_locks: dict[str, asyncio.Lock] = {}
    title_tasks: dict[tuple[Path, str], asyncio.Task] = {}

    async def active_library(request: Request):
        assistant_id = request.path_params.get("assistant_id")
        if assistant_id is None:
            # Preserve the original API for existing local/CLI integrations.
            yield library
            return
        selected = assistants.library(assistant_id)
        assistants.inflight[assistant_id] = assistants.inflight.get(assistant_id, 0) + 1
        try:
            yield selected
        finally:
            assistants.inflight[assistant_id] -= 1

    async def title_session(session_id, question, settings):
        title = None
        try:
            if answer is ask_agent:
                async with AsyncOpenAI(
                    api_key=require_openai_key(settings), timeout=40, max_retries=1
                ) as client:
                    title = await generate_title(question, client=client, settings=settings)
            else:
                title = await generate_title(question, client=None, settings=settings)
        except asyncio.CancelledError:
            raise
        except (OpenAIError, ValueError, RuntimeError):
            logger.warning("Unable to generate a conversation title")
        finally:
            # No await between loading and saving: preserve any newly saved answer or memory.
            saved = load_session(session_id, settings=settings)
            saved["title"] = title or "تعذر تسمية المحادثة"
            saved["title_status"] = "ready" if title else "error"
            if title:
                saved.pop("title_question", None)
            save_session(saved, settings=settings, preserve_title=False)

    def start_title(session_id, question, settings):
        key = (settings.chat_sessions_dir, session_id)
        task = title_tasks.get(key)
        if task is not None and not task.done():
            return
        task = asyncio.create_task(title_session(session_id, question, settings))
        title_tasks[key] = task

        def finished(task):
            title_tasks.pop(key, None)
            if not task.cancelled() and task.exception() is not None:
                logger.error(
                    "Conversation title job failed for %s", session_id, exc_info=task.exception()
                )

        task.add_done_callback(finished)

    @asynccontextmanager
    async def lifespan(app):
        # One web worker owns the durable job queue. CLI writes use the index write lock.
        lock = FileLock(str(runtime_settings.web_data_dir / ".app.lock"))
        lock.acquire(timeout=0)
        try:
            await library.start()
            await assistants.start()
            # Resume title work interrupted by a previous process exiting.
            for selected in [library, *assistants.libraries.values()]:
                settings = selected.settings
                for path in settings.chat_sessions_dir.glob("*.json"):
                    try:
                        saved = load_session(path.stem, settings=settings)
                        if saved["title_status"] == "pending":
                            start_title(path.stem, saved["title_question"], settings)
                    except (ValueError, FileNotFoundError):
                        logger.warning("Skipping unreadable session file %s", path.name)
            yield
        finally:
            tasks = list(title_tasks.values())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.gather(library.close(), assistants.close())
            lock.release()

    app = FastAPI(title="Advanced RAG Library", lifespan=lifespan)
    app.state.assistants = assistants

    def all_libraries():
        return [
            library,
            *(
                selected
                for assistant_id, selected in assistants.libraries.items()
                if assistant_id not in assistants.deleting
            ),
        ]

    def embedding_locked():
        for selected in all_libraries():
            selected.list()
        return any(selected.has_documents for selected in all_libraries())

    @app.get("/api/assistants")
    async def list_assistants():
        return assistants.list()

    @app.post("/api/assistants", status_code=201)
    async def create_assistant(body: AssistantFields):
        return await assistants.create(body)

    @app.get("/api/assistants/{assistant_id}")
    async def read_assistant(assistant_id: str):
        return assistants.get(assistant_id)

    @app.put("/api/assistants/{assistant_id}")
    async def update_assistant(assistant_id: str, body: AssistantFields):
        return assistants.update(assistant_id, body)

    @app.delete("/api/assistants/{assistant_id}", status_code=204)
    async def delete_assistant(assistant_id: str):
        selected = assistants.library(assistant_id)
        assistants.begin_delete(assistant_id)
        tasks = [
            task
            for (directory, _), task in title_tasks.items()
            if directory == selected.settings.chat_sessions_dir
        ]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await assistants.finish_delete(assistant_id)
        return Response(status_code=204)

    @app.exception_handler(RequestValidationError)
    async def bad_request(request: Request, exc):
        # Pydantic includes input values by default, which could expose credentials.
        return JSONResponse(
            {"detail": "قيمة غير صالحة في الطلب. راجع الحقول وحاول مجددًا."}, status_code=422
        )

    @app.get("/api/settings")
    async def read_settings():
        return {**web_settings.public(), "embedding_locked": embedding_locked()}

    @app.put("/api/settings")
    async def save_settings(body: SettingsPatch):
        nonlocal runtime_settings
        if (
            library.mutation_lock.locked()
            or any(
                job.task and not job.task.done()
                for selected in all_libraries()
                for job in selected.jobs.values()
            )
            or any(lock.locked() for lock in session_locks.values())
            or any(assistants.inflight.values())
            or assistants.deleting
        ):
            raise LibraryConflict("انتظر اكتمال التدريب أو الإجابة الحالية قبل حفظ الإعدادات.")
        locked = embedding_locked()
        if (
            body.embedding_model
            and body.embedding_model != runtime_settings.embedding_model
            and locked
        ):
            raise LibraryConflict(
                "أزل فهرسة الملفات المدرّبة قبل تغيير مودل embeddings، ثم درّبها مجددًا."
            )
        runtime_settings = web_settings.save(body)
        library.update_settings(runtime_settings)
        assistants.update_settings(runtime_settings)
        return {**web_settings.public(), "embedding_locked": locked}

    @app.exception_handler(FileNotFoundError)
    async def not_found(request: Request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(LibraryConflict)
    async def conflict(request: Request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc):
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/health")
    async def health():
        return {
            "status": "ok",
            "max_upload_bytes": runtime_settings.max_upload_bytes,
            "doc_available": libreoffice_executable(runtime_settings) is not None,
        }

    @app.get("/api/files")
    @workspace.get("/files")
    async def files(library: Annotated[Library, Depends(active_library)]):
        return library.list()

    @app.post("/api/files", status_code=201)
    @workspace.post("/files", status_code=201)
    async def upload(file: UploadFile, library: Annotated[Library, Depends(active_library)]):
        name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        suffix = Path(name).suffix.lower()
        if suffix not in SUPPORTED or not name or len(name) > 255:
            raise ValueError("الصيغ المدعومة: PDF وDOCX وDOC وTXT.")
        file_id = str(uuid4())
        original = file_id + suffix
        path = library.registry.uploads / original
        size = 0
        try:
            with path.open("wb") as output:
                while block := await file.read(1024 * 1024):
                    size += len(block)
                    if size > library.settings.max_upload_bytes:
                        return JSONResponse(
                            {"detail": "حجم الملف أكبر من الحد المسموح."}, status_code=413
                        )
                    await asyncio.to_thread(output.write, block)
            if size == 0:
                raise ValueError("لا يمكن رفع ملف فارغ.")
            if suffix == ".pdf":
                with path.open("rb") as source:
                    if b"%PDF-" not in source.read(1024):
                        raise ValueError("الملف المرفوع ليس PDF صالحًا.")
            row = library.registry.add(
                name, size, file_id=file_id, original=original, image_support=suffix == ".pdf"
            )
            return library.registry.public(row)
        finally:
            await file.close()
            try:
                library.registry.get(file_id)
            except FileNotFoundError:
                path.unlink(missing_ok=True)

    @app.post("/api/files/{file_id}/train")
    @workspace.post("/files/{file_id}/train")
    async def train(file_id: str, library: Annotated[Library, Depends(active_library)]):
        row = library.train(file_id)
        return JSONResponse(row, status_code=200 if row["status"] == "trained" else 202)

    @app.post("/api/files/{file_id}/cancel")
    @workspace.post("/files/{file_id}/cancel")
    async def cancel(file_id: str, library: Annotated[Library, Depends(active_library)]):
        return await library.cancel(file_id)

    @app.post("/api/files/{file_id}/unindex")
    @workspace.post("/files/{file_id}/unindex")
    async def unindex(file_id: str, library: Annotated[Library, Depends(active_library)]):
        return await library.remove(file_id)

    @app.delete("/api/files/{file_id}", status_code=204)
    @workspace.delete("/files/{file_id}", status_code=204)
    async def delete(file_id: str, library: Annotated[Library, Depends(active_library)]):
        await library.remove(file_id, delete=True)
        return Response(status_code=204)

    @app.get("/api/files/{file_id}/download")
    @workspace.get("/files/{file_id}/download")
    async def download(file_id: str, library: Annotated[Library, Depends(active_library)]):
        row = library.registry.get(file_id)
        if not row["original"]:
            raise FileNotFoundError("الملف الأصلي غير متوفر؛ أُضيف من سطر الأوامر.")
        return FileResponse(library.registry.uploads / row["original"], filename=row["name"])

    @app.get("/api/sources/{chunk_id}")
    @workspace.get("/sources/{chunk_id}")
    async def source(
        chunk_id: str, request: Request, library: Annotated[Library, Depends(active_library)]
    ):
        result = library.source(chunk_id)
        assistant_id = request.path_params.get("assistant_id")
        if assistant_id:
            for image in result.get("images", []):
                image["url"] = (
                    f"/api/assistants/{assistant_id}/sources/{chunk_id}/images/{image['id']}"
                )
        return result

    @app.get("/api/sources/{chunk_id}/images/{image_id}")
    @workspace.get("/sources/{chunk_id}/images/{image_id}")
    async def source_image(
        chunk_id: str, image_id: str, library: Annotated[Library, Depends(active_library)]
    ):
        return FileResponse(
            library.image(chunk_id, image_id),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    def session_summary(session, path):
        turns = session["turns"]
        return {
            "id": session["session_id"],
            "title": session.get("title")
            or (fallback_title(turns[0]["question"]) if turns else "محادثة جديدة"),
            "turns": len(turns),
            "title_status": session["title_status"],
            "updated_at": path.stat().st_mtime,
        }

    @app.get("/api/sessions")
    @workspace.get("/sessions")
    async def sessions(library: Annotated[Library, Depends(active_library)]):
        summaries = []
        for path in library.settings.chat_sessions_dir.glob("*.json"):
            try:
                session = load_session(path.stem, settings=library.settings)
                summaries.append(session_summary(session, path))
            except (ValueError, FileNotFoundError):
                logger.warning("Skipping unreadable session file %s", path.name)
        return sorted(summaries, key=lambda row: row["updated_at"], reverse=True)

    @app.post("/api/sessions", status_code=201)
    @workspace.post("/sessions", status_code=201)
    async def new_session(library: Annotated[Library, Depends(active_library)]):
        session = load_session(None, settings=library.settings)
        save_session(session, settings=library.settings)
        return session

    @app.get("/api/sessions/{session_id}")
    @workspace.get("/sessions/{session_id}")
    async def session(session_id: str, library: Annotated[Library, Depends(active_library)]):
        return load_session(session_id, settings=library.settings)

    @app.post("/api/sessions/{session_id}/title", status_code=202)
    @workspace.post("/sessions/{session_id}/title", status_code=202)
    async def retry_title(session_id: str, library: Annotated[Library, Depends(active_library)]):
        settings = library.settings
        saved = load_session(session_id, settings=settings)
        if saved["title_status"] == "pending":
            return {"title": saved["title"], "title_status": "pending"}
        question = saved.get("title_question") or (
            saved["turns"][0]["question"] if saved["turns"] else None
        )
        if not question:
            raise ValueError("أرسل أول رسالة قبل توليد عنوان المحادثة.")
        saved["title_status"] = "pending"
        saved["title_question"] = question
        save_session(saved, settings=settings, preserve_title=False)
        start_title(session_id, question, settings)
        return {"title": saved["title"], "title_status": "pending"}

    @app.post("/api/sessions/{session_id}/messages")
    @workspace.post("/sessions/{session_id}/messages")
    async def send(
        session_id: str, body: Question, library: Annotated[Library, Depends(active_library)]
    ):
        settings = library.settings
        load_session(session_id, settings=settings)
        if not body.question.strip():
            raise ValueError("اكتب سؤالك أولًا.")
        lock = session_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise LibraryConflict("هناك إجابة قيد التجهيز في هذه المحادثة.")

        async def answer_with_title(client):
            result = await answer(
                body.question,
                context=library.context if library.has_documents else None,
                client=client,
                settings=settings,
                session_id=session_id,
            )
            saved = load_session(session_id, settings=settings)
            return {**result, "title": saved["title"], "title_status": saved["title_status"]}

        try:
            async with lock:
                saved = load_session(session_id, settings=settings)
                if saved["title_status"] == "idle" and not saved["turns"]:
                    saved["title_status"] = "pending"
                    saved["title_question"] = body.question
                    save_session(saved, settings=settings, preserve_title=False)
                    start_title(session_id, body.question, settings)
                if answer is not ask_agent:
                    return await answer_with_title(None)
                async with AsyncOpenAI(
                    api_key=require_openai_key(settings), timeout=60, max_retries=1
                ) as client:
                    return await answer_with_title(client)
        except RerankingError:
            logger.exception("Local document reranking failed")
            return JSONResponse(
                {
                    "detail": "تعذر ترتيب نتائج الملفات بالمودل المحلي BGE. تأكد من اكتمال تنزيل النموذج وتوفر ذاكرة كافية، ثم أعد المحاولة."
                },
                status_code=502,
            )
        except MemoryContextError as exc:
            logger.exception("Conversation exceeds model context capacity")
            return JSONResponse({"detail": str(exc)}, status_code=422)
        except (OpenAIError, RuntimeError):
            logger.exception("Chat request failed")
            return JSONResponse(
                {
                    "detail": "تعذر تجهيز الإجابة. تحقق من اتصال خدمة الذكاء الاصطناعي ثم أعد المحاولة."
                },
                status_code=502,
            )

    app.include_router(workspace)
    dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    else:

        @app.get("/")
        async def missing_frontend():
            return {
                "message": "Build the React client: cd frontend && npm install && npm run build"
            }

    return app


def main():
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
