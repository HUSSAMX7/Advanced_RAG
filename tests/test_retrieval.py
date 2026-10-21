import asyncio

import pytest
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode

from advanced_rag import Settings
from advanced_rag.retrieval import load_search_context, search_documents
from advanced_rag.storage import store_in_faiss


@pytest.fixture
def section_corpus(tmp_path, local_reranker):
    settings = Settings(
        _env_file=None,
        faiss_persist_dir=tmp_path / "index",
        retrieval_candidates=2,
        retrieval_top_k=1,
        rerank_model=local_reranker.model_name,
    )
    embedding = MockEmbedding(embed_dim=2)
    common = {
        "resource_id": "file-a",
        "source": "shared.pdf",
        "section_id": "1: Policy",
        "sub_section_id": "1.1: Leave",
    }
    nodes = [
        TextNode(
            id_="late",
            text="Carryover details",
            embedding=[0.6, 0.6],
            metadata={**common, "page_num": 3},
        ),
        TextNode(
            id_="seed",
            text="Invoice ZX-774",
            embedding=[0.5, 0.5],
            metadata={**common, "page_num": 2},
        ),
        TextNode(
            id_="early",
            text="Eligibility details",
            embedding=[9.0, 9.0],
            metadata={**common, "page_num": 1},
        ),
        TextNode(
            id_="other-sub",
            text="Remote work",
            embedding=[8.0, 8.0],
            metadata={**common, "sub_section_id": "1.2: Remote", "page_num": 4},
        ),
        TextNode(
            id_="other-section",
            text="Equipment",
            embedding=[8.0, 8.0],
            metadata={**common, "section_id": "2: Equipment", "page_num": 5},
        ),
        TextNode(
            id_="other-file",
            text="Unrelated report",
            embedding=[0.7, 0.7],
            metadata={**common, "resource_id": "file-b", "page_num": 1},
        ),
        TextNode(
            id_="unclassified",
            text="Unclassified notes",
            embedding=[8.0, 8.0],
            metadata={"resource_id": "file-a", "source": "shared.pdf"},
        ),
    ]
    store_in_faiss(nodes, settings, embed_model=embedding)
    return settings, load_search_context(settings, embed_model=embedding)


@pytest.mark.parametrize("legacy", [False, True])
def test_expand_subsection_in_page_order_without_crossing_files(
    section_corpus, local_reranker, legacy
):
    settings, context = section_corpus
    if legacy:
        for node in context["nodes"]:
            node.metadata.pop("resource_id", None)
            if node.node_id == "other-file":
                node.metadata["source"] = "other.pdf"
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))

    assert [hit["chunk_id"] for hit in hits] == ["early", "seed", "late"]
    assert [hit["metadata"]["page_num"] for hit in hits] == [1, 2, 3]
    assert hits[0]["text"] == "Eligibility details"
    # The expanded context includes a passage outside the initial candidate pool.
    assert len(local_reranker.calls[0]) == 2
    assert all(text != "Eligibility details" for _, text in local_reranker.calls[0])


@pytest.mark.parametrize("subsection", [None, "1: Policy"])
def test_expand_main_section_when_seed_has_no_distinct_subsection(section_corpus, subsection):
    settings, context = section_corpus
    seed = next(node for node in context["nodes"] if node.node_id == "seed")
    seed.metadata["sub_section_id"] = subsection
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == ["early", "seed", "late", "other-sub"]


def test_overlapping_seed_sections_are_expanded_once(section_corpus):
    settings, context = section_corpus
    settings.retrieval_top_k = 2
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == ["early", "seed", "late"]


def test_expansion_keeps_document_groups_in_seed_rank_order(section_corpus):
    settings, context = section_corpus
    settings.retrieval_candidates = len(context["nodes"])
    settings.retrieval_top_k = 2
    foreign = next(node for node in context["nodes"] if node.node_id == "other-file")
    foreign.text = "Invoice from another project"
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == ["early", "seed", "late", "other-file"]


def test_expansion_preserves_stored_chunk_order_within_a_page(section_corpus):
    settings, context = section_corpus
    for node in context["nodes"]:
        node.metadata["page_num"] = 1
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == ["late", "seed", "early"]


def test_filename_section_fallback_expands_the_whole_file(section_corpus):
    settings, context = section_corpus
    for node in context["nodes"]:
        if node.metadata["resource_id"] == "file-a":
            node.metadata.update(section_id="0: shared.pdf", sub_section_id="0: shared.pdf")
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == [
        "unclassified",
        "early",
        "seed",
        "late",
        "other-sub",
        "other-section",
    ]


@pytest.mark.parametrize("missing", ["section", "file"])
def test_missing_expansion_metadata_keeps_original_hit(section_corpus, missing):
    settings, context = section_corpus
    seed = next(node for node in context["nodes"] if node.node_id == "seed")
    fields = ("section_id",) if missing == "section" else ("resource_id", "source")
    for field in fields:
        seed.metadata.pop(field, None)
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert [hit["chunk_id"] for hit in hits] == ["seed"]


def test_expanded_visuals_expose_original_evidence_only(section_corpus):
    settings, context = section_corpus
    visual = next(node for node in context["nodes"] if node.node_id == "late")
    visual.text = "Generated description, not source evidence"
    visual.metadata.update(node_kind="image_description", original_text="Original figure caption")
    hits = asyncio.run(search_documents("ZX-774", context=context, settings=settings))
    assert hits[-1]["text"] == "Original figure caption"
    assert all("Generated description" not in hit["text"] for hit in hits)
    assert all("original_text" not in hit["metadata"] for hit in hits)


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
