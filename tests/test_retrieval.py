import asyncio
import json

import httpx
import pytest
from conftest import api_client, response_payload
from llama_index.core.schema import TextNode

from advanced_rag.retrieval import load_search_context, search_documents
from advanced_rag.storage import store_in_faiss


def test_hybrid_search_can_rerank_an_exact_identifier_ahead_of_a_semantic_hit(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)

    def respond(request):
        body = json.loads(request.content)
        candidates = json.loads(body["input"][0]["content"])["candidates"]
        assert {hit["chunk_id"] for hit in candidates} == {"identifier", "semantic"}
        return httpx.Response(
            200, json=response_payload({"ordered_ids": ["identifier", "semantic"]})
        )

    async def run():
        async with api_client(respond) as client:
            return await search_documents(
                "ZX-774", context=context, client=client, settings=settings
            )

    hits = asyncio.run(run())
    assert [hit["chunk_id"] for hit in hits] == ["identifier"]
    assert hits[0]["text"] == "Invoice ZX-774 costs 120 dollars"
    assert hits[0]["metadata"]["page_num"] == 3


def test_arabic_keyword_normalization_preserves_original_excerpt_values(corpus):
    settings, embedding = corpus
    original = "أَسْعَارُ المنتج ١٢٠ ريالًا بتاريخ 2026-10-08"
    store_in_faiss(
        [
            TextNode(
                id_="arabic",
                text=original,
                embedding=[9.0, 9.0],
                metadata={"source": "أسعار.pdf", "page_num": 4},
            )
        ],
        settings,
        embed_model=embedding,
    )
    context = load_search_context(settings, embed_model=embedding)

    def respond(request):
        candidates = json.loads(json.loads(request.content)["input"][0]["content"])["candidates"]
        assert {hit["chunk_id"] for hit in candidates} == {"arabic", "semantic"}
        return httpx.Response(200, json=response_payload({"ordered_ids": ["arabic", "semantic"]}))

    async def run():
        async with api_client(respond) as client:
            return await search_documents(
                "اسعار", context=context, client=client, settings=settings
            )

    assert asyncio.run(run())[0]["text"] == original


@pytest.mark.parametrize(
    "ranking",
    [
        {"ordered_ids": ["identifier", "identifier"]},
        {"ordered_ids": ["fabricated", "semantic"]},
        {"ordered_ids": ["identifier"]},
        {"ordered_ids": None},
    ],
)
def test_invalid_reranking_fails_instead_of_returning_unranked_results(corpus, ranking):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)

    async def run():
        async with api_client(
            lambda request: httpx.Response(200, json=response_payload(ranking))
        ) as client:
            return await search_documents(
                "ZX-774", context=context, client=client, settings=settings
            )

    with pytest.raises(RuntimeError, match="invalid ranking"):
        asyncio.run(run())


def test_incomplete_reranking_is_a_failure(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    payload = response_payload({"ordered_ids": ["identifier", "semantic"]})
    payload["status"] = "incomplete"

    async def run():
        async with api_client(lambda request: httpx.Response(200, json=payload)) as client:
            return await search_documents(
                "ZX-774", context=context, client=client, settings=settings
            )

    with pytest.raises(RuntimeError, match="did not complete"):
        asyncio.run(run())


def test_missing_index_has_a_clear_error(corpus, tmp_path):
    settings, embedding = corpus
    settings.faiss_persist_dir = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="FAISS index directory not found"):
        load_search_context(settings, embed_model=embedding)
