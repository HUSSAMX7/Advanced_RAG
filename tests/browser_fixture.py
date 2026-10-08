"""Isolated browser QA with local embeddings and deterministic answers, never live services.

Run: uv run python tests/browser_fixture.py
The disposable library is removed when this server shuts down.
"""

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from llama_index.core.embeddings import MockEmbedding

from advanced_rag import Settings
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.ingestion.documents import prepare_document
from advanced_rag.web.app import create_app


async def prepare(resource, settings, progress):
    progress("extracting")
    await asyncio.sleep(3)
    return await prepare_document(resource, settings, progress)


async def answer(question, *, context, client, settings, session_id):
    await asyncio.sleep(0.15)
    node = context["nodes"][0]
    text = "قيمة الفاتورة ZX-774 هي 120 دولارًا. [1]"
    sources = [{"chunk_id": node.node_id, "citation": 1, "metadata": node.metadata}]
    session = load_session(session_id, settings=settings)
    session["turns"].append({"question": question, "answer": text, "sources": sources})
    save_session(session, settings=settings)
    return {"answer": text, "sources": sources, "session_id": session_id}


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="rag-browser-qa-") as directory:
        root = Path(directory)
        settings = Settings(
            _env_file=None,
            web_data_dir=root / "library",
            faiss_persist_dir=root / "index",
            chat_sessions_dir=root / "sessions",
        )
        uvicorn.run(
            create_app(
                settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2), answer=answer
            ),
            host="127.0.0.1",
            port=8002,
        )
