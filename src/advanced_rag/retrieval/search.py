"""Combine FAISS and lexical rankings without mixing their different scores."""

import re
from collections import defaultdict

from rank_bm25 import BM25Okapi

from ..config import Settings
from ..storage import load_faiss_index
from ..visuals import evidence_metadata, evidence_text
from .reranking import rerank_chunks
from .types import SearchContext, SearchHit


def _tokens(text: str) -> list[str]:
    text = re.sub(r"[\u0610-\u061a\u064b-\u065f\u0670\u0640]", "", text.lower())
    text = text.translate(str.maketrans("أإآٱ", "اااا"))
    return re.findall(r"\w+(?:[-./@]\w+)*", text)


def load_search_context(settings: Settings, *, embed_model=None) -> SearchContext:
    """Load the saved index and build lexical search over its indexed chunks only."""
    if not settings.faiss_persist_dir.is_dir():
        raise FileNotFoundError(f"FAISS index directory not found: {settings.faiss_persist_dir}")
    index = load_faiss_index(settings, embed_model=embed_model)
    node_ids = list(index.index_struct.nodes_dict.values())
    if len(node_ids) != index.vector_store.client.ntotal or len(set(node_ids)) != len(node_ids):
        raise ValueError("FAISS vectors and saved chunk mappings are inconsistent")
    nodes = index.docstore.get_nodes(node_ids)
    tokenized = [
        _tokens(
            "\n".join(
                [
                    node.get_content(),
                    str(node.metadata.get("source", "")),
                    str(node.metadata.get("section_id", "")),
                    str(node.metadata.get("sub_section_id", "")),
                ]
            )
        )
        for node in nodes
    ]
    return {
        "index": index,
        "nodes": nodes,
        "tokens": [set(tokens) for tokens in tokenized],
        "bm25": BM25Okapi(tokenized) if any(tokenized) else None,
    }


async def search_documents(
    query: str,
    *,
    context: SearchContext,
    settings: Settings,
) -> list[SearchHit]:
    """Search all documents, fuse rankings, and return reranked text with metadata."""
    if not query.strip():
        raise ValueError("Search query cannot be empty")
    if not context["nodes"]:
        return []
    limit = min(settings.retrieval_candidates, len(context["nodes"]))
    dense = await context["index"].as_retriever(similarity_top_k=limit).aretrieve(query)
    query_tokens = _tokens(query)
    lexical_ids = []
    if context["bm25"] is not None and query_tokens:
        scores = context["bm25"].get_scores(query_tokens)
        matching = [
            i for i, tokens in enumerate(context["tokens"]) if tokens.intersection(query_tokens)
        ]
        matching.sort(key=lambda i: (-scores[i], context["nodes"][i].node_id))
        lexical_ids = [context["nodes"][i].node_id for i in matching[:limit]]
    fused: dict[str, float] = defaultdict(float)
    for ranking in [[hit.node.node_id for hit in dense], lexical_ids]:
        for rank, chunk_id in enumerate(dict.fromkeys(ranking), start=1):
            fused[chunk_id] += 1.0 / (60 + rank)
    selected = sorted(fused, key=lambda chunk_id: (-fused[chunk_id], chunk_id))[:limit]
    by_id = {node.node_id: node for node in context["nodes"]}
    candidates: list[SearchHit] = [
        {
            "chunk_id": chunk_id,
            "text": by_id[chunk_id].get_content(),
            "metadata": dict(by_id[chunk_id].metadata),
        }
        for chunk_id in selected
    ]
    ranked = await rerank_chunks(query, candidates, settings=settings)
    # Descriptions participate in retrieval/reranking, but never become answer evidence.
    return [
        {
            "chunk_id": hit["chunk_id"],
            "text": evidence_text(by_id[hit["chunk_id"]]),
            "metadata": evidence_metadata(hit["metadata"]),
        }
        for hit in ranked[: settings.retrieval_top_k]
    ]
