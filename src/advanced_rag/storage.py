"""Persist FAISS vectors together with LlamaIndex text nodes and metadata."""

import faiss
from llama_index.core import StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.schema import MetadataMode, TextNode
from llama_index.vector_stores.faiss import FaissVectorStore

from .config import Settings, require_openai_key


def _embedding_model(settings: Settings, embed_model=None):
    if embed_model is not None:
        return embed_model
    from llama_index.embeddings.openai import OpenAIEmbedding

    return OpenAIEmbedding(
        model=settings.embedding_model,
        api_key=require_openai_key(settings),
    )


def load_faiss_index(settings: Settings, *, embed_model=None) -> VectorStoreIndex:
    """Reload the vectors, node text, metadata, and vector-to-node mapping."""
    embedding = _embedding_model(settings, embed_model)
    directory = str(settings.faiss_persist_dir)
    vector_store = FaissVectorStore.from_persist_dir(directory)
    context = StorageContext.from_defaults(persist_dir=directory, vector_store=vector_store)
    return load_index_from_storage(context, embed_model=embedding)


def store_in_faiss(
    nodes: list[TextNode],
    settings: Settings,
    *,
    embed_model=None,
) -> None:
    """Create or append to the local index, then save its complete storage context."""
    if not nodes:
        raise ValueError("No chunks to store")
    embedding = _embedding_model(settings, embed_model)
    # Use the actual embedding dimension, including when a different model is supplied.
    if nodes[0].embedding is None:
        nodes[0].embedding = embedding.get_text_embedding(
            nodes[0].get_content(metadata_mode=MetadataMode.EMBED)
        )
    dimension = len(nodes[0].get_embedding())
    directory = settings.faiss_persist_dir
    if directory.is_dir() and any(directory.iterdir()):
        index = load_faiss_index(settings, embed_model=embedding)
        if index.vector_store.client.d != dimension:
            raise ValueError("Embedding dimension differs from the saved FAISS index")
        index.insert_nodes(nodes)
    else:
        vector_store = FaissVectorStore(faiss_index=faiss.IndexFlatL2(dimension))
        context = StorageContext.from_defaults(vector_store=vector_store)
        index = VectorStoreIndex(nodes=nodes, storage_context=context, embed_model=embedding)
    index.storage_context.persist(persist_dir=str(directory))
