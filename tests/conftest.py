import json

import httpx
import pytest
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from openai import AsyncOpenAI

from advanced_rag import Settings
from advanced_rag.storage import store_in_faiss


def response_payload(data, response_id="resp_test"):
    return {
        "id": response_id,
        "object": "response",
        "created_at": 0,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [
            {
                "id": "msg_test",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": json.dumps(data), "annotations": []}],
            }
        ],
    }


@pytest.fixture
def corpus(tmp_path):
    settings = Settings(
        _env_file=None,
        faiss_persist_dir=tmp_path / "index",
        chat_sessions_dir=tmp_path / "sessions",
        retrieval_candidates=2,
        retrieval_top_k=1,
    )
    embedding = MockEmbedding(embed_dim=2)
    store_in_faiss(
        [
            TextNode(
                id_="semantic",
                text="Budget revenue plan",
                embedding=[0.5, 0.5],
                metadata={"source": "budget.pdf", "page_num": 1, "section_id": "1: Budget"},
            ),
            TextNode(
                id_="identifier",
                text="Invoice ZX-774 costs 120 dollars",
                embedding=[8.0, 8.0],
                metadata={"source": "invoice.pdf", "page_num": 3, "section_id": "2: Invoices"},
            ),
            TextNode(
                id_="unrelated",
                text="Unrelated notes",
                embedding=[5.0, 5.0],
                metadata={"source": "notes.pdf", "page_num": 2},
            ),
        ],
        settings,
        embed_model=embedding,
    )
    return settings, embedding


def api_client(handler):
    return AsyncOpenAI(
        api_key="test-key",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
