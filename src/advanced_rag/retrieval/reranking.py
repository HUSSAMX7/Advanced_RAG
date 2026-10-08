"""Score query/excerpt pairs locally with a cached BGE cross-encoder."""

import asyncio
import math
import threading
from functools import lru_cache

from ..config import Settings
from .types import SearchHit

_inference_lock = threading.Lock()


class RerankingError(RuntimeError):
    """The local relevance model could not produce valid scores."""


@lru_cache(maxsize=1)
def _load_model(model_name: str, max_length: int):
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model_name, device="cpu", max_length=max_length)


def _rank(query: str, candidates: list[SearchHit], settings: Settings) -> list[SearchHit]:
    try:
        # Serialize loading and inference: concurrent requests share one model in memory.
        with _inference_lock:
            model = _load_model(settings.rerank_model, settings.rerank_max_length)
            raw_scores = model.predict(
                [(query, hit["text"]) for hit in candidates],
                batch_size=settings.rerank_batch_size,
                show_progress_bar=False,
            )
    except Exception as exc:
        raise RerankingError(
            "Local BGE reranking failed. Check the model cache, download connection, and available memory."
        ) from exc
    try:
        scores = [float(score) for score in raw_scores]
        if len(scores) != len(candidates) or not all(math.isfinite(score) for score in scores):
            raise ValueError("Expected one finite score per candidate")
    except (ValueError, TypeError, OverflowError) as exc:
        raise RerankingError("Local BGE returned invalid relevance scores") from exc
    order = sorted(range(len(candidates)), key=lambda i: scores[i], reverse=True)
    return [candidates[i] for i in order]


async def rerank_chunks(
    query: str,
    candidates: list[SearchHit],
    *,
    settings: Settings,
) -> list[SearchHit]:
    """Preserve excerpts/metadata and sort by relevance without blocking the event loop."""
    if not candidates:
        return []
    if not query.strip():
        raise ValueError("Search query cannot be empty")
    return await asyncio.to_thread(_rank, query, candidates, settings)
