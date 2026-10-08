"""Disposable visual-source browser QA; uses mocked API responses and local embeddings.

Run: .venv/Scripts/python.exe tests/visual_browser_fixture.py
"""

import asyncio
import tempfile
from pathlib import Path

import uvicorn
from llama_index.core.embeddings import MockEmbedding
from test_visuals import enrich, pdf_resource

from advanced_rag import Settings
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.storage import store_in_faiss
from advanced_rag.visuals import evidence_metadata
from advanced_rag.web.app import create_app
from advanced_rag.web.registry import Registry

if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="rag-visual-qa-") as directory:
        root = Path(directory)
        settings = Settings(
            _env_file=None,
            web_data_dir=root / "library",
            faiss_persist_dir=root / "index",
            chat_sessions_dir=root / "sessions",
        )
        embedding = MockEmbedding(embed_dim=2)
        resource = pdf_resource()
        registry = Registry(settings.web_data_dir)
        original = f"{resource['resource_id']}.pdf"
        (registry.uploads / original).write_bytes(resource["data"])
        registry.add(
            resource["file_name"],
            len(resource["data"]),
            file_id=resource["resource_id"],
            original=original,
            image_support=True,
        )
        nodes = asyncio.run(enrich(resource, settings))
        store_in_faiss(nodes, settings, embed_model=embedding)
        node = next(node for node in nodes if node.metadata.get("node_kind") == "image_description")
        session = load_session(None, settings=settings)
        session["turns"].append(
            {
                "question": "ما لون المحرك في الشكل؟",
                "answer": "الشكل يوضح المحرك باللون الأحمر. [1]",
                "sources": [
                    {
                        "chunk_id": node.node_id,
                        "citation": 1,
                        "metadata": evidence_metadata(node.metadata),
                    }
                ],
            }
        )
        save_session(session, settings=settings)
        uvicorn.run(create_app(settings, embed_model=embedding), host="127.0.0.1", port=8003)
