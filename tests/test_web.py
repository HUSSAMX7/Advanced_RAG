import asyncio
import threading
import time

import pytest
from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode

from advanced_rag import Settings
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.storage import load_faiss_index
from advanced_rag.web.app import create_app


def web_settings(tmp_path):
    return Settings(
        _env_file=None,
        web_data_dir=tmp_path / "library",
        faiss_persist_dir=tmp_path / "index",
        chat_sessions_dir=tmp_path / "sessions",
    )


def wait_status(client, file_id, expected):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = next(row for row in client.get("/api/files").json() if row["id"] == file_id)
        if row["status"] == expected:
            return row
        time.sleep(0.01)
    raise AssertionError(f"Expected {expected}; got {row}")


def test_upload_train_unindex_retrain_delete_survives_restart(tmp_path):
    settings = web_settings(tmp_path)
    embedding = MockEmbedding(embed_dim=2)
    with TestClient(create_app(settings, embed_model=embedding)) as client:
        response = client.post("/api/files", files={"file": ("notes.txt", b"Important notes")})
        assert response.status_code == 201
        row = response.json()
        assert row["status"] == "untrained"
        assert client.post(f"/api/files/{row['id']}/train").status_code == 202
        assert wait_status(client, row["id"], "trained")["chunks"] == 1
        assert client.post(f"/api/files/{row['id']}/train").status_code == 200
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 1
        assert client.post(f"/api/files/{row['id']}/unindex").json()["status"] == "untrained"
        assert client.get(f"/api/files/{row['id']}/download").content == b"Important notes"
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 0
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
    with TestClient(create_app(settings, embed_model=embedding)) as client:
        assert client.get("/api/files").json()[0]["status"] == "trained"
        assert client.delete(f"/api/files/{row['id']}").status_code == 204
        assert client.get("/api/files").json() == []
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 0


def test_cancelled_training_does_not_publish_and_can_be_retried(tmp_path):
    settings = web_settings(tmp_path)

    async def prepare(resource, settings, progress):
        progress("extracting")
        await asyncio.sleep(0.15)
        return [TextNode(text="test", metadata={"resource_id": resource["resource_id"]})]

    with TestClient(
        create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"notes")}).json()
        client.post(f"/api/files/{row['id']}/train")
        assert client.post(f"/api/files/{row['id']}/cancel").status_code == 200
        wait_status(client, row["id"], "cancelled")
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")


def test_chat_resumes_sessions_and_sources_become_unavailable_after_deletion(tmp_path):
    settings = web_settings(tmp_path)

    async def answer(question, *, context, settings, session_id, client):
        if callable(context):
            context = await context()
        node = context["nodes"][0]
        result = {
            "answer": "Important notes [1]",
            "sources": [{"chunk_id": node.node_id, "citation": 1, "metadata": node.metadata}],
            "session_id": session_id,
        }
        session = load_session(session_id, settings=settings)
        session["turns"].append(
            {"question": question, "answer": result["answer"], "sources": result["sources"]}
        )
        save_session(session, settings=settings)
        return result

    with TestClient(
        create_app(settings, embed_model=MockEmbedding(embed_dim=2), answer=answer)
    ) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"Important notes")}).json()
        session = client.post("/api/sessions").json()
        session_id = session["session_id"]
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
        result = client.post(
            f"/api/sessions/{session_id}/messages", json={"question": "What is important?"}
        ).json()
        chunk_id = result["sources"][0]["chunk_id"]
        assert client.get(f"/api/sources/{chunk_id}").json()["text"] == "Important notes"
        assert client.get("/api/sessions").json()[0]["title"] == "What is important?"
        client.delete(f"/api/files/{row['id']}")
        assert client.get(f"/api/sources/{chunk_id}").json()["available"] is False
        assert (
            client.get(f"/api/sessions/{session_id}").json()["turns"][0]["answer"]
            == "Important notes [1]"
        )


@pytest.mark.parametrize("library_state", ["empty", "uploaded", "unindexed", "deleted"])
def test_general_chat_is_saved_and_resumed_without_trained_files(tmp_path, library_state):
    settings = web_settings(tmp_path)

    async def answer(question, *, context, settings, session_id, client):
        assert context is None
        session = load_session(session_id, settings=settings)
        text = "General answer" if not session["turns"] else "Follow-up answer"
        session["turns"].append({"question": question, "answer": text, "sources": []})
        save_session(session, settings=settings)
        return {"answer": text, "sources": [], "session_id": session_id}

    with TestClient(
        create_app(settings, embed_model=MockEmbedding(embed_dim=2), answer=answer)
    ) as client:
        if library_state != "empty":
            row = client.post("/api/files", files={"file": ("notes.txt", b"notes")}).json()
            if library_state in {"unindexed", "deleted"}:
                client.post(f"/api/files/{row['id']}/train")
                wait_status(client, row["id"], "trained")
                if library_state == "unindexed":
                    client.post(f"/api/files/{row['id']}/unindex")
                else:
                    client.delete(f"/api/files/{row['id']}")
        session_id = client.post("/api/sessions").json()["session_id"]
        first = client.post(f"/api/sessions/{session_id}/messages", json={"question": "Hello"})
        assert first.status_code == 200
        assert first.json()["answer"] == "General answer"
        assert first.json()["sources"] == []
        second = client.post(
            f"/api/sessions/{session_id}/messages", json={"question": "Explain more"}
        )
        assert second.status_code == 200
        assert second.json()["answer"] == "Follow-up answer"
    with TestClient(create_app(settings, answer=answer)) as client:
        assert len(client.get(f"/api/sessions/{session_id}").json()["turns"]) == 2


def test_general_chat_does_not_wait_for_first_file_training(tmp_path):
    settings = web_settings(tmp_path)
    started = threading.Event()
    release = threading.Event()
    answered = threading.Event()

    async def prepare(resource, settings, progress):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        return [TextNode(text="notes", metadata={"resource_id": resource["resource_id"]})]

    async def answer(question, *, context, settings, session_id, client):
        assert context is None
        answered.set()
        return {"answer": "Hello", "sources": [], "session_id": session_id}

    with TestClient(
        create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2), answer=answer)
    ) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"notes")}).json()
        client.post(f"/api/files/{row['id']}/train")
        assert started.wait(timeout=3)
        session_id = client.post("/api/sessions").json()["session_id"]
        responses = []
        request_thread = threading.Thread(
            target=lambda: responses.append(
                client.post(f"/api/sessions/{session_id}/messages", json={"question": "Hello"})
            )
        )
        request_thread.start()
        try:
            assert answered.wait(timeout=2), "General chat waited for training"
        finally:
            release.set()
            request_thread.join(timeout=5)
        assert responses[0].status_code == 200
        wait_status(client, row["id"], "trained")


def test_general_chat_and_polling_work_during_embeddings_with_an_existing_library(tmp_path):
    settings = web_settings(tmp_path)
    block = threading.Event()
    started = threading.Event()
    release = threading.Event()

    class GatedEmbedding(MockEmbedding):
        def get_text_embedding_batch(self, texts, **kwargs):
            if block.is_set():
                started.set()
                assert release.wait(timeout=5)
            return super().get_text_embedding_batch(texts, **kwargs)

    embedding = GatedEmbedding(embed_dim=2)

    async def answer(question, *, context, settings, session_id, client):
        assert callable(context)
        return {"answer": "General answer", "sources": [], "session_id": session_id}

    with TestClient(create_app(settings, embed_model=embedding, answer=answer)) as client:
        first = client.post("/api/files", files={"file": ("first.txt", b"first")}).json()
        client.post(f"/api/files/{first['id']}/train")
        wait_status(client, first["id"], "trained")
    block.set()
    with TestClient(create_app(settings, embed_model=embedding, answer=answer)) as client:
        second = client.post("/api/files", files={"file": ("second.txt", b"second")}).json()
        client.post(f"/api/files/{second['id']}/train")
        assert started.wait(timeout=3)
        cancellations = []
        cancel_thread = threading.Thread(
            target=lambda: cancellations.append(client.post(f"/api/files/{second['id']}/cancel"))
        )
        try:
            session_id = client.post("/api/sessions").json()["session_id"]
            response = client.post(
                f"/api/sessions/{session_id}/messages", json={"question": "Hello"}
            )
            assert response.status_code == 200
            assert response.json()["answer"] == "General answer"
            assert client.get("/api/files").status_code == 200
            assert client.get("/api/health").status_code == 200
            cancel_thread.start()
            wait_status(client, second["id"], "cancelling")
            assert client.get("/api/health").status_code == 200
        finally:
            release.set()
            if cancel_thread.ident is not None:
                cancel_thread.join(timeout=5)
        assert cancellations[0].status_code == 200
        wait_status(client, second["id"], "cancelled")
        assert len(client.get("/api/files").json()) == 2


def test_cancel_queued_work_does_not_wait_for_the_running_job_or_leak_the_writer_lock(tmp_path):
    settings = web_settings(tmp_path)
    started = threading.Event()
    release = threading.Event()

    async def prepare(resource, settings, progress):
        progress("extracting")
        if resource["file_name"] == "first.txt":
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.01)
        return [
            TextNode(text=resource["file_name"], metadata={"resource_id": resource["resource_id"]})
        ]

    with TestClient(
        create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        first = client.post("/api/files", files={"file": ("first.txt", b"first")}).json()
        second = client.post("/api/files", files={"file": ("second.txt", b"second")}).json()
        client.post(f"/api/files/{first['id']}/train")
        assert started.wait(timeout=3)
        try:
            client.post(f"/api/files/{second['id']}/train")
            assert client.post(f"/api/files/{second['id']}/cancel").json()["status"] == "cancelled"
            assert (
                next(row for row in client.get("/api/files").json() if row["id"] == first["id"])[
                    "status"
                ]
                == "training"
            )
        finally:
            release.set()
        wait_status(client, first["id"], "trained")
        client.post(f"/api/files/{second['id']}/train")
        wait_status(client, second["id"], "trained")


def test_unsupported_empty_oversized_and_spoofed_pdf_uploads_leave_no_files(tmp_path):
    settings = web_settings(tmp_path).model_copy(update={"max_upload_bytes": 8})
    with TestClient(create_app(settings)) as client:
        for name, content, expected in [
            ("notes.exe", b"text", 400),
            ("notes.txt", b"", 400),
            ("notes.txt", b"012345678", 413),
            ("fake.pdf", b"notpdf", 400),
        ]:
            assert (
                client.post("/api/files", files={"file": (name, content)}).status_code == expected
            )
        assert client.get("/api/files").json() == []
        assert list((settings.web_data_dir / "uploads").iterdir()) == []


def test_same_file_name_does_not_merge_uploaded_documents(tmp_path):
    settings = web_settings(tmp_path)
    embedding = MockEmbedding(embed_dim=2)
    with TestClient(create_app(settings, embed_model=embedding)) as client:
        first = client.post("/api/files", files={"file": ("same.txt", b"first document")}).json()
        second = client.post("/api/files", files={"file": ("same.txt", b"second document")}).json()
        for row in [first, second]:
            client.post(f"/api/files/{row['id']}/train")
            wait_status(client, row["id"], "trained")
        client.delete(f"/api/files/{first['id']}")
        index = load_faiss_index(settings, embed_model=embedding)
        nodes = index.docstore.get_nodes(list(index.index_struct.nodes_dict.values()))
        assert [node.text for node in nodes] == ["second document"]


def test_publication_is_recovered_if_status_write_was_interrupted(tmp_path):
    import sqlite3

    settings = web_settings(tmp_path)
    embedding = MockEmbedding(embed_dim=2)
    with TestClient(create_app(settings, embed_model=embedding)) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"Important notes")}).json()
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
    # Simulate a process exiting after publishing the index but before updating SQLite.
    with sqlite3.connect(settings.web_data_dir / "library.sqlite3") as connection:
        connection.execute(
            "UPDATE files SET status='training', stage='storing' WHERE id=?", (row["id"],)
        )
    with TestClient(create_app(settings, embed_model=embedding)) as client:
        recovered = client.get("/api/files").json()[0]
        assert recovered["status"] == "trained"
        assert recovered["chunks"] == 1
        assert client.post(f"/api/files/{row['id']}/train").status_code == 200
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 1


def test_failure_preserves_prior_corpus_and_retries_without_duplicate_vectors(tmp_path):
    settings = web_settings(tmp_path)
    fail = threading.Event()

    async def prepare(resource, settings, progress):
        if fail.is_set():
            raise ValueError("فشل استخراج النص")
        return [TextNode(text="test", metadata={"resource_id": resource["resource_id"]})]

    embedding = MockEmbedding(embed_dim=2)
    with TestClient(create_app(settings, prepare=prepare, embed_model=embedding)) as client:
        first = client.post("/api/files", files={"file": ("first.txt", b"first")}).json()
        second = client.post("/api/files", files={"file": ("second.txt", b"second")}).json()
        client.post(f"/api/files/{first['id']}/train")
        wait_status(client, first["id"], "trained")
        fail.set()
        client.post(f"/api/files/{second['id']}/train")
        assert wait_status(client, second["id"], "failed")["error"] == "فشل استخراج النص"
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 1
        fail.clear()
        client.post(f"/api/files/{second['id']}/train")
        wait_status(client, second["id"], "trained")
        assert load_faiss_index(settings, embed_model=embedding).vector_store.client.ntotal == 2
