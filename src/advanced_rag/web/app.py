"""FastAPI host for the local library and the built React client."""

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from openai import AsyncOpenAI, OpenAIError
from pydantic import BaseModel, Field

from ..agent import ask_agent
from ..agent.sessions import load_session, save_session
from ..config import Settings, require_openai_key
from ..ingestion.documents import libreoffice_executable, prepare_document
from ..retrieval.reranking import RerankingError
from .library import Library, LibraryConflict

logger = logging.getLogger(__name__)
SUPPORTED = {".pdf", ".doc", ".docx", ".txt"}


class Question(BaseModel):
    question: str = Field(min_length=1, max_length=12000)


def create_app(settings=None, *, prepare=prepare_document, embed_model=None, answer=ask_agent):
    settings = settings or Settings()
    library = Library(settings, prepare=prepare, embed_model=embed_model)
    session_locks: dict[str, asyncio.Lock] = {}

    @asynccontextmanager
    async def lifespan(app):
        # One web worker owns the durable job queue. CLI writes use the index write lock.
        lock = FileLock(str(settings.web_data_dir / ".app.lock"))
        lock.acquire(timeout=0)
        try:
            await library.start()
            yield
        finally:
            await library.close()
            lock.release()

    app = FastAPI(title="Advanced RAG Library", lifespan=lifespan)

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
            "max_upload_bytes": settings.max_upload_bytes,
            "doc_available": libreoffice_executable(settings) is not None,
        }

    @app.get("/api/files")
    async def files():
        return library.list()

    @app.post("/api/files", status_code=201)
    async def upload(file: UploadFile):
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
                    if size > settings.max_upload_bytes:
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
            row = library.registry.add(name, size, file_id=file_id, original=original)
            return library.registry.public(row)
        finally:
            await file.close()
            try:
                library.registry.get(file_id)
            except FileNotFoundError:
                path.unlink(missing_ok=True)

    @app.post("/api/files/{file_id}/train")
    async def train(file_id: str):
        row = library.train(file_id)
        return JSONResponse(row, status_code=200 if row["status"] == "trained" else 202)

    @app.post("/api/files/{file_id}/cancel")
    async def cancel(file_id: str):
        return await library.cancel(file_id)

    @app.post("/api/files/{file_id}/unindex")
    async def unindex(file_id: str):
        return await library.remove(file_id)

    @app.delete("/api/files/{file_id}", status_code=204)
    async def delete(file_id: str):
        await library.remove(file_id, delete=True)
        return Response(status_code=204)

    @app.get("/api/files/{file_id}/download")
    async def download(file_id: str):
        row = library.registry.get(file_id)
        if not row["original"]:
            raise FileNotFoundError("الملف الأصلي غير متوفر؛ أُضيف من سطر الأوامر.")
        return FileResponse(library.registry.uploads / row["original"], filename=row["name"])

    @app.get("/api/sources/{chunk_id}")
    async def source(chunk_id: str):
        return library.source(chunk_id)

    def session_summary(session, path):
        turns = session["turns"]
        return {
            "id": session["session_id"],
            "title": turns[0]["question"][:65] if turns else "محادثة جديدة",
            "turns": len(turns),
            "updated_at": path.stat().st_mtime,
        }

    @app.get("/api/sessions")
    async def sessions():
        summaries = []
        for path in settings.chat_sessions_dir.glob("*.json"):
            try:
                session = load_session(path.stem, settings=settings)
                summaries.append(session_summary(session, path))
            except (ValueError, FileNotFoundError):
                logger.warning("Skipping unreadable session file %s", path.name)
        return sorted(summaries, key=lambda row: row["updated_at"], reverse=True)

    @app.post("/api/sessions", status_code=201)
    async def new_session():
        session = load_session(None, settings=settings)
        save_session(session, settings=settings)
        return session

    @app.get("/api/sessions/{session_id}")
    async def session(session_id: str):
        return load_session(session_id, settings=settings)

    @app.post("/api/sessions/{session_id}/messages")
    async def send(session_id: str, body: Question):
        load_session(session_id, settings=settings)
        if not body.question.strip():
            raise ValueError("اكتب سؤالك أولًا.")
        lock = session_locks.setdefault(session_id, asyncio.Lock())
        if lock.locked():
            raise LibraryConflict("هناك إجابة قيد التجهيز في هذه المحادثة.")
        try:
            async with lock:
                context = library.context if library.has_documents else None
                if answer is not ask_agent:
                    return await answer(
                        body.question,
                        context=context,
                        client=None,
                        settings=settings,
                        session_id=session_id,
                    )
                async with AsyncOpenAI(
                    api_key=require_openai_key(settings), timeout=60, max_retries=1
                ) as client:
                    return await answer(
                        body.question,
                        context=context,
                        client=client,
                        settings=settings,
                        session_id=session_id,
                    )
        except RerankingError:
            logger.exception("Local document reranking failed")
            return JSONResponse(
                {
                    "detail": "تعذر ترتيب نتائج الملفات بالمودل المحلي BGE. تأكد من اكتمال تنزيل النموذج وتوفر ذاكرة كافية، ثم أعد المحاولة."
                },
                status_code=502,
            )
        except (OpenAIError, RuntimeError):
            logger.exception("Chat request failed")
            return JSONResponse(
                {
                    "detail": "تعذر تجهيز الإجابة. تحقق من اتصال خدمة الذكاء الاصطناعي ثم أعد المحاولة."
                },
                status_code=502,
            )

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
