"""Publish complete FAISS generations without modifying the active index in place."""

import json
import shutil
from collections.abc import Callable
from contextlib import nullcontext
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import faiss
from filelock import FileLock
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import MetadataMode, TextNode
from llama_index.vector_stores.faiss import FaissVectorStore

from .config import Settings, require_openai_key


class TrainingCancelled(Exception):
    """An unpublished index generation was discarded."""


def _embedding_model(settings: Settings, embed_model=None):
    if embed_model is not None:
        return embed_model
    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(model=settings.embedding_model, api_key=require_openai_key(settings))


def active_index_directory(settings: Settings) -> Path:
    """Resolve the atomic pointer, accepting indexes saved before generations existed."""
    base = settings.faiss_persist_dir
    pointer = base / "current.json"
    if not pointer.exists():
        return base
    generation = json.loads(pointer.read_text(encoding="utf-8"))["generation"]
    if str(UUID(generation)) != generation:
        raise ValueError("Invalid index generation")
    return base / "versions" / generation


def index_revision(settings: Settings) -> str:
    pointer = settings.faiss_persist_dir / "current.json"
    if pointer.exists():
        return pointer.read_text(encoding="utf-8")
    legacy = settings.faiss_persist_dir / "docstore.json"
    return str(legacy.stat().st_mtime_ns) if legacy.exists() else "empty"


def committed_file_counts(settings: Settings) -> dict[str, int]:
    """Read completion markers without acquiring the writer lock during cancellation."""
    pointer = settings.faiss_persist_dir / "current.json"
    if not pointer.exists():
        return {}
    counts = json.loads(pointer.read_text(encoding="utf-8")).get("files", {})
    if not isinstance(counts, dict) or any(
        not isinstance(key, str) or not isinstance(value, int) or value < 0
        for key, value in counts.items()
    ):
        raise ValueError("Invalid index completion markers")
    return counts


def file_key(node) -> str:
    """Identify both uploaded files and legacy CLI documents consistently."""
    name = str(node.metadata.get("source", node.metadata.get("paper_path", "")))
    return str(node.metadata.get("resource_id") or uuid5(NAMESPACE_URL, "legacy:" + name))


def load_faiss_index(settings: Settings, *, embed_model=None) -> VectorStoreIndex:
    if not settings.faiss_persist_dir.is_dir():
        raise FileNotFoundError(f"FAISS index directory not found: {settings.faiss_persist_dir}")
    with FileLock(str(settings.faiss_persist_dir / ".write.lock")):
        directory = str(active_index_directory(settings))
        vector_store = FaissVectorStore.from_persist_dir(directory)
        context = StorageContext.from_defaults(persist_dir=directory, vector_store=vector_store)
        index = load_index_from_storage(
            context, embed_model=_embedding_model(settings, embed_model)
        )
        if not isinstance(index, VectorStoreIndex):
            raise ValueError("Saved index is not a vector index")  # noqa: TRY004 - persisted data
        return index


def read_index_nodes(settings: Settings) -> tuple[list[TextNode], int]:
    """Read persisted text and reuse its exact vectors, without any network requests."""
    if not settings.faiss_persist_dir.is_dir():
        return [], 0
    with FileLock(str(settings.faiss_persist_dir / ".write.lock")):
        return _read_index_nodes(settings)


def _read_index_nodes(settings: Settings) -> tuple[list[TextNode], int]:
    directory = active_index_directory(settings)
    if not (directory / "docstore.json").exists():
        return [], 0
    vector_store = FaissVectorStore.from_persist_dir(str(directory))
    context = StorageContext.from_defaults(persist_dir=str(directory), vector_store=vector_store)
    dimension = vector_store.client.d
    index = load_index_from_storage(context, embed_model=MockEmbedding(embed_dim=dimension))
    mapping = index.index_struct.nodes_dict
    if len(mapping) != vector_store.client.ntotal:
        raise ValueError("FAISS vectors and saved chunks are inconsistent")
    nodes = []
    for row, node_id in sorted(mapping.items(), key=lambda item: int(item[0])):
        node = index.docstore.get_node(node_id).model_copy(deep=True)
        if not isinstance(node, TextNode):
            raise ValueError("Saved vector is not linked to a text chunk")  # noqa: TRY004 - persisted data
        node.embedding = vector_store.client.reconstruct(int(row)).tolist()
        nodes.append(node)
    return nodes, dimension


def _publish(nodes, dimension, settings, embedding, cancelled, commit_lock=None):
    if cancelled():
        raise TrainingCancelled()
    base = settings.faiss_persist_dir
    generation = str(uuid4())
    directory = base / "versions" / generation
    pointer = base / f"current.{generation}.tmp"
    published = False
    try:
        vector_store = FaissVectorStore(faiss_index=faiss.IndexFlatL2(dimension))
        context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex(nodes=nodes, storage_context=context, embed_model=embedding)
        if cancelled():
            raise TrainingCancelled()
        index.storage_context.persist(persist_dir=str(directory))
        counts = {}
        for node in nodes:
            key = file_key(node)
            counts[key] = counts.get(key, 0) + 1
        pointer.write_text(
            json.dumps({"generation": generation, "files": counts}), encoding="utf-8"
        )
        # Accepted cancellation and publication share a lock across the worker thread.
        with commit_lock if commit_lock is not None else nullcontext():
            if cancelled():
                raise TrainingCancelled()
            pointer.replace(base / "current.json")
            published = True
    finally:
        pointer.unlink(missing_ok=True)
        if not published:
            shutil.rmtree(directory, ignore_errors=True)
    versions = base / "versions"
    for old in versions.iterdir():
        if old != directory:
            shutil.rmtree(old, ignore_errors=True)


def store_in_faiss(
    nodes: list[TextNode],
    settings: Settings,
    *,
    embed_model=None,
    cancelled: Callable[[], bool] = lambda: False,
    commit_lock=None,
) -> None:
    """Append in a staged generation; retrying a file replaces its previous chunks."""
    if not nodes:
        raise ValueError("No chunks to store")
    if cancelled():
        raise TrainingCancelled()
    base = settings.faiss_persist_dir
    base.mkdir(parents=True, exist_ok=True)
    with FileLock(str(base / ".write.lock")):
        existing, dimension = _read_index_nodes(settings)
        embedding = _embedding_model(settings, embed_model)
        missing = [node for node in nodes if node.embedding is None]
        if missing:
            batch_size = min(embedding.embed_batch_size, 32)
            for start in range(0, len(missing), batch_size):
                if cancelled():
                    raise TrainingCancelled()
                batch = missing[start : start + batch_size]
                vectors = embedding.get_text_embedding_batch(
                    [node.get_content(metadata_mode=MetadataMode.EMBED) for node in batch]
                )
                if cancelled():
                    raise TrainingCancelled()
                for node, vector in zip(batch, vectors, strict=True):
                    node.embedding = vector
        new_dimension = len(nodes[0].get_embedding())
        if dimension and dimension != new_dimension:
            raise ValueError("Embedding dimension differs from the saved FAISS index")
        if any(len(node.get_embedding()) != new_dimension for node in nodes):
            raise ValueError("Inconsistent embedding dimensions")
        ids = {
            str(node.metadata["resource_id"]) for node in nodes if "resource_id" in node.metadata
        }
        kept = [node for node in existing if file_key(node) not in ids]
        _publish(kept + nodes, new_dimension, settings, embedding, cancelled, commit_lock)


def remove_file_from_faiss(file_id: str, settings: Settings, *, by_source: bool = False) -> None:
    """Rebuild from retained vectors without re-embedding or requiring an API key."""
    base = settings.faiss_persist_dir
    base.mkdir(parents=True, exist_ok=True)
    with FileLock(str(base / ".write.lock")):
        nodes, dimension = _read_index_nodes(settings)
        kept = [
            node
            for node in nodes
            if (str(node.metadata.get("source")) if by_source else file_key(node)) != file_id
        ]
        if len(kept) == len(nodes):
            return
        _publish(kept, dimension, settings, MockEmbedding(embed_dim=dimension), lambda: False)
