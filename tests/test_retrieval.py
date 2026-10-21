import asyncio

import pytest
from llama_index.core.schema import TextNode

from advanced_rag.retrieval import load_search_context, search_documents
from advanced_rag.storage import store_in_faiss


def test_hybrid_search_can_rerank_an_exact_identifier_ahead_of_a_semantic_hit(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)

    async def run():
        return await search_documents("ZX-774", context=context, settings=settings)

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

    async def run():
        return await search_documents("اسعار", context=context, settings=settings)

    assert asyncio.run(run())[0]["text"] == original


@pytest.mark.parametrize("scores", [[0.5], [0.5, float("nan")], [float("inf"), 0.1], ["bad", 0.1]])
def test_invalid_local_scores_fail_instead_of_returning_unranked_results(
    corpus, local_reranker, scores
):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    local_reranker.scores = scores

    with pytest.raises(RuntimeError, match="invalid relevance scores"):
        asyncio.run(search_documents("ZX-774", context=context, settings=settings))


def test_local_reranker_is_reused_and_ties_preserve_retrieval_order(corpus, local_reranker):
    settings, embedding = corpus
    settings.retrieval_top_k = 2
    context = load_search_context(settings, embed_model=embedding)
    local_reranker.scores = [1.0, 1.0]

    async def run():
        first = await search_documents("ZX-774", context=context, settings=settings)
        second = await search_documents("ZX-774", context=context, settings=settings)
        return first, second

    first, second = asyncio.run(run())
    assert [hit["chunk_id"] for hit in first] == ["identifier", "semantic"]
    assert first == second
    assert local_reranker.loads == 1
    assert len(local_reranker.calls) == 2
    assert all(query == "ZX-774" for query, _ in local_reranker.calls[0])


def test_missing_index_has_a_clear_error(corpus, tmp_path):
    settings, embedding = corpus
    settings.faiss_persist_dir = tmp_path / "missing"
    with pytest.raises(FileNotFoundError, match="FAISS index directory not found"):
        load_search_context(settings, embed_model=embedding)
