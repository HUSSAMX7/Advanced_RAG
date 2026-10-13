"""Conversation, title scheduling and answer orchestration."""

import asyncio
import logging

from openai import AsyncOpenAI, OpenAIError

from ...agent import ask_agent
from ...agent.titles import fallback_title, generate_title
from ...config import require_openai_key
from ..files import processing
from ..files.processing import LibraryConflict
from . import repository

logger = logging.getLogger(__name__)


async def title_session(workspace, session_id, question, settings):
    title = None
    try:
        if workspace.answer is ask_agent:
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
        saved = repository.load(settings, session_id)
        saved["title"] = title or "تعذر تسمية المحادثة"
        saved["title_status"] = "ready" if title else "error"
        if title:
            saved.pop("title_question", None)
        repository.save(settings, saved, preserve_title=False)


def start_title(workspace, session_id, question, settings):
    key = (settings.chat_sessions_dir, session_id)
    task = workspace.title_tasks.get(key)
    if task is not None and not task.done():
        return
    task = asyncio.create_task(title_session(workspace, session_id, question, settings))
    workspace.title_tasks[key] = task

    def finished(task):
        workspace.title_tasks.pop(key, None)
        if not task.cancelled() and task.exception() is not None:
            logger.error(
                "Conversation title job failed for %s", session_id, exc_info=task.exception()
            )

    task.add_done_callback(finished)


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


async def list_conversations(library):
    summaries = []
    for path in repository.paths(library.settings):
        try:
            session = repository.load(library.settings, path.stem)
            summaries.append(session_summary(session, path))
        except (ValueError, FileNotFoundError):
            logger.warning("Skipping unreadable session file %s", path.name)
    return sorted(summaries, key=lambda row: row["updated_at"], reverse=True)


async def new_conversation(library):
    session = repository.load(library.settings, None)
    repository.save(library.settings, session)
    return session


async def read_conversation(session_id, library):
    return repository.load(library.settings, session_id)


async def retry_title(workspace, session_id, library):
    settings = library.settings
    saved = repository.load(settings, session_id)
    if saved["title_status"] == "pending":
        return {"title": saved["title"], "title_status": "pending"}
    question = saved.get("title_question") or (
        saved["turns"][0]["question"] if saved["turns"] else None
    )
    if not question:
        raise ValueError("أرسل أول رسالة قبل توليد عنوان المحادثة.")
    saved["title_status"] = "pending"
    saved["title_question"] = question
    repository.save(settings, saved, preserve_title=False)
    start_title(workspace, session_id, question, settings)
    return {"title": saved["title"], "title_status": "pending"}


async def send(workspace, session_id, body, library):
    settings = library.settings
    repository.load(settings, session_id)
    if not body.question.strip():
        raise ValueError("اكتب سؤالك أولًا.")
    if workspace.answer is ask_agent:
        require_openai_key(settings)
    lock = workspace.session_locks.setdefault(session_id, asyncio.Lock())
    if lock.locked():
        raise LibraryConflict("هناك إجابة قيد التجهيز في هذه المحادثة.")

    async def answer_with_title(client):
        result = await workspace.answer(
            body.question,
            context=(lambda: processing.context(library))
            if processing.has_documents(library)
            else None,
            client=client,
            settings=settings,
            session_id=session_id,
        )
        saved = repository.load(settings, session_id)
        return {**result, "title": saved["title"], "title_status": saved["title_status"]}

    async with lock:
        saved = repository.load(settings, session_id)
        if saved["title_status"] == "idle" and not saved["turns"]:
            saved["title_status"] = "pending"
            saved["title_question"] = body.question
            repository.save(settings, saved, preserve_title=False)
            start_title(workspace, session_id, body.question, settings)
        if workspace.answer is not ask_agent:
            return await answer_with_title(None)
        async with AsyncOpenAI(
            api_key=require_openai_key(settings), timeout=60, max_retries=1
        ) as client:
            return await answer_with_title(client)


async def resume_titles(workspace):
    for library in [workspace.library, *workspace.assistants.libraries.values()]:
        settings = library.settings
        for path in repository.paths(settings):
            try:
                saved = repository.load(settings, path.stem)
                if saved["title_status"] == "pending":
                    start_title(workspace, path.stem, saved["title_question"], settings)
            except (ValueError, FileNotFoundError):
                logger.warning("Skipping unreadable session file %s", path.name)


async def close(workspace):
    tasks = list(workspace.title_tasks.values())
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
