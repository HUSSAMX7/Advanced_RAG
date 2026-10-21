"""Conversation HTTP routes."""

import logging

from fastapi import APIRouter, HTTPException
from openai import OpenAIError

from ...agent.memory import MemoryContextError
from ...retrieval.reranking import RerankingError
from ..dependencies import LibraryDependency, WorkspaceDependency
from . import services
from .schemas import Question

logger = logging.getLogger(__name__)


def create_router(prefix):
    router = APIRouter(prefix=prefix, tags=["conversations"])

    @router.get("/sessions")
    async def sessions(library: LibraryDependency):
        return await services.list_conversations(library)

    @router.post("/sessions", status_code=201)
    async def new_session(library: LibraryDependency):
        return await services.new_conversation(library)

    @router.get("/sessions/{session_id}")
    async def session(session_id: str, library: LibraryDependency):
        return await services.read_conversation(session_id, library)

    @router.post("/sessions/{session_id}/title", status_code=202)
    async def retry_title(
        session_id: str, library: LibraryDependency, workspace: WorkspaceDependency
    ):
        return await services.retry_title(workspace, session_id, library)

    @router.post("/sessions/{session_id}/messages")
    async def send(
        session_id: str, body: Question, library: LibraryDependency, workspace: WorkspaceDependency
    ):
        try:
            return await services.send(workspace, session_id, body, library)
        except RerankingError as exc:
            logger.exception("Local reranking failed")
            raise HTTPException(
                502,
                "تعذر ترتيب نتائج الملفات بالمودل المحلي BGE. تأكد من اكتمال تنزيل النموذج وتوفر ذاكرة كافية، ثم أعد المحاولة.",
            ) from exc
        except MemoryContextError as exc:
            raise HTTPException(422, str(exc)) from exc
        except (OpenAIError, RuntimeError) as exc:
            logger.exception("Unable to answer conversation")
            raise HTTPException(
                502, "تعذر تجهيز الإجابة. تحقق من اتصال خدمة الذكاء الاصطناعي ثم أعد المحاولة."
            ) from exc

    return router
