from llama_index.core.schema import TextNode

from advanced_rag.storage import load_faiss_index, remove_file_from_faiss, store_in_faiss


def test_removing_a_file_preserves_other_vectors_and_can_remove_the_last_file(corpus):
    settings, embedding = corpus
    remove_file_from_faiss("invoice.pdf", settings, by_source=True)
    index = load_faiss_index(settings, embed_model=embedding)
    nodes = index.docstore.get_nodes(list(index.index_struct.nodes_dict.values()))
    assert {node.metadata["source"] for node in nodes} == {"budget.pdf", "notes.pdf"}
    assert index.vector_store.client.ntotal == 2
    remove_file_from_faiss("budget.pdf", settings, by_source=True)
    remove_file_from_faiss("notes.pdf", settings, by_source=True)
    assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 0


def test_cancel_before_publication_leaves_the_previous_index_unchanged(corpus):
    import pytest

    from advanced_rag.storage import TrainingCancelled

    settings, embedding = corpus
    with pytest.raises(TrainingCancelled):
        store_in_faiss(
            [TextNode(text="Do not publish", metadata={"resource_id": "cancelled"})],
            settings,
            embed_model=embedding,
            cancelled=lambda: True,
        )
    assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 3


def test_cancelling_during_embedding_discards_the_new_generation(corpus):
    import threading

    import pytest
    from llama_index.core.embeddings import MockEmbedding

    from advanced_rag.storage import TrainingCancelled

    settings, embedding = corpus
    event = threading.Event()
    embedded_texts = []

    class CancellingEmbedding(MockEmbedding):
        def _get_text_embedding(self, text):
            embedded_texts.append(text)
            event.set()
            return super()._get_text_embedding(text)

    with pytest.raises(TrainingCancelled):
        store_in_faiss(
            [
                TextNode(text=f"Not committed {i}", metadata={"resource_id": "cancelled"})
                for i in range(4)
            ],
            settings,
            embed_model=CancellingEmbedding(embed_dim=2, embed_batch_size=1),
            cancelled=event.is_set,
        )
    assert len(embedded_texts) == 1
    assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 3
