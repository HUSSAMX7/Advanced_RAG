"""Combine FAISS and lexical rankings without mixing their different scores."""

import re
from collections import defaultdict

from llama_index.core.schema import BaseNode
from rank_bm25 import BM25Okapi

from ..config import Settings
from ..storage import file_key, load_faiss_index
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


def _file_scope(node: BaseNode) -> str | None:
    metadata = node.metadata
    if metadata.get("resource_id") or metadata.get("source") or metadata.get("paper_path"):
        return file_key(node)
    return None


def _page_number(node: BaseNode) -> int:
    try:
        return int(node.metadata.get("page_num", 0))
    except (TypeError, ValueError, OverflowError):
        return 0


def _expand_sections(seeds: list[SearchHit], nodes: list[BaseNode]) -> list[BaseNode]:
    """Expand ranked seeds within their file, preserving original citation IDs.

    Files follow their first seed's rank; passages within each file follow page
    and persisted chunk order. Missing section or file identity keeps the seed.
    """
    by_id = {node.node_id: node for node in nodes}
    positions = {node.node_id: position for position, node in enumerate(nodes)}
    scopes = {node.node_id: _file_scope(node) for node in nodes}
    sections: dict[tuple[str, str], list[BaseNode]] = defaultdict(list)
    for node in nodes:
        scope = scopes[node.node_id]
        section = node.metadata.get("section_id")
        if scope and isinstance(section, str) and section.strip():
            sections[scope, section].append(node)

    expanded: dict[str, BaseNode] = {}
    file_order: dict[str, int] = {}
    did_expand = False
    for hit in seeds:
        seed = by_id[hit["chunk_id"]]
        scope = scopes[seed.node_id]
        file_order.setdefault(scope or seed.node_id, len(file_order))
        section = seed.metadata.get("section_id")
        members = sections.get((scope, section), []) if scope and isinstance(section, str) else []
        subsection = seed.metadata.get("sub_section_id")
        if isinstance(subsection, str) and subsection.strip() and subsection != section:
            members = [
                node for node in members if node.metadata.get("sub_section_id") == subsection
            ] or members
        did_expand = did_expand or len(members) > 1
        for node in members or [seed]:
            expanded.setdefault(node.node_id, node)

    if not did_expand:
        return list(expanded.values())
    return sorted(
        expanded.values(),
        key=lambda node: (
            file_order[scopes[node.node_id] or node.node_id],
            _page_number(node),
            positions[node.node_id],
        ),
    )


async def search_documents(
    query: str,
    *,
    context: SearchContext,
    settings: Settings,
) -> list[SearchHit]:
    """Find and rerank seed chunks, then expand their sections into source evidence."""
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
    expanded = _expand_sections(ranked[: settings.retrieval_top_k], context["nodes"])
    # Descriptions participate in retrieval/reranking, but never become answer evidence.
    return [
        {
            "chunk_id": node.node_id,
            "text": evidence_text(node),
            "metadata": evidence_metadata(node.metadata),
        }
        for node in expanded
    ]
