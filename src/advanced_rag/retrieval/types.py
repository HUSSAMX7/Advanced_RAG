"""Dictionary interfaces for retrieval functions."""

from typing import Any, TypedDict

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import BaseNode
from rank_bm25 import BM25Okapi

SearchHit = TypedDict(
    "SearchHit",
    {
        "chunk_id": str,
        "text": str,
        "metadata": dict[str, Any],
    },
)
SearchContext = TypedDict(
    "SearchContext",
    {
        "index": VectorStoreIndex,
        "nodes": list[BaseNode],
        "tokens": list[set[str]],
        "bm25": BM25Okapi | None,
    },
)
