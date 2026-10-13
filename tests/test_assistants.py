import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from PIL import Image
from test_web import web_settings

from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.storage import read_index_nodes
from advanced_rag.visuals import image_path
from advanced_rag.web.app import create_app


def create(client, name="الموارد البشرية", **fields):
    response = client.post("/api/assistants", json={"name": name, **fields})
    assert response.status_code == 201
    row = response.json()
    return row, f"/api/assistants/{row['id']}"


def train(client, base, text):
    response = client.post(base + "/files", files={"file": ("notes.txt", text.encode())})
    assert response.status_code == 201
    file_id = response.json()["id"]
    assert client.post(f"{base}/files/{file_id}/train").status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        row = client.get(base + "/files").json()[0]
        if row["status"] == "trained":
            return file_id
        time.sleep(0.01)
    raise AssertionError(row)


def test_assistant_libraries_search_sources_and_history_are_isolated_and_persist(tmp_path):
    settings = web_settings(tmp_path)
    seen = []

    async def answer(question, *, context, settings, session_id, client):
        context = await context()
        node = context["nodes"][0]
        seen.append((node.text, settings.assistant_instructions))
        sources = [{"chunk_id": node.node_id, "citation": 1, "metadata": node.metadata}]
        session = load_session(session_id, settings=settings)
        session["turns"].append({"question": question, "answer": node.text, "sources": sources})
        save_session(session, settings=settings)
        return {"answer": node.text, "sources": sources, "session_id": session_id}

    with TestClient(
        create_app(settings, embed_model=MockEmbedding(embed_dim=2), answer=answer)
    ) as client:
        assert client.get("/api/assistants").json() == []
        a, a_base = create(client, instructions="أجب باختصار")
        b, b_base = create(client, "المالية", instructions="أجب بالتفصيل")
        a_file = train(client, a_base, "HR policy: 30 days")
        train(client, b_base, "Finance: invoice 120 dollars")
        a_session = client.post(a_base + "/sessions").json()["session_id"]
        b_session = client.post(b_base + "/sessions").json()["session_id"]
        a_reply = client.post(
            f"{a_base}/sessions/{a_session}/messages", json={"question": "التفاصيل؟"}
        )
        b_reply = client.post(
            f"{b_base}/sessions/{b_session}/messages", json={"question": "التفاصيل؟"}
        )
        assert a_reply.status_code == b_reply.status_code == 200
        assert a_reply.json()["answer"] == "HR policy: 30 days"
        assert b_reply.json()["answer"] == "Finance: invoice 120 dollars"
        assert seen == [
            ("HR policy: 30 days", "أجب باختصار"),
            ("Finance: invoice 120 dollars", "أجب بالتفصيل"),
        ]
        chunk = a_reply.json()["sources"][0]["chunk_id"]
        assert client.get(f"{a_base}/sources/{chunk}").json()["available"]
        assert not client.get(f"{b_base}/sources/{chunk}").json()["available"]
        assert client.get(f"{b_base}/sources/{chunk}/images/unknown").status_code == 404
        assert client.get(f"{b_base}/files/{a_file}/download").status_code == 404
        for operation in ("train", "cancel", "unindex"):
            assert client.post(f"{b_base}/files/{a_file}/{operation}").status_code == 404
        assert client.delete(f"{b_base}/files/{a_file}").status_code == 404
        assert client.get(f"{b_base}/sessions/{a_session}").status_code == 404
        assert (
            client.post(
                f"{b_base}/sessions/{a_session}/messages", json={"question": "Hi"}
            ).status_code
            == 404
        )
        assert client.post(f"{b_base}/sessions/{a_session}/title").status_code == 404
        # The compatibility API cannot access the assistants' private stores either.
        assert client.get("/api/files").json() == []
        assert client.get("/api/sessions").json() == []
        assert client.get(f"/api/files/{a_file}/download").status_code == 404
        assert client.get(f"/api/sessions/{a_session}").status_code == 404
        cards = client.get("/api/assistants").json()
        assert [(row["files"], row["trained"], row["conversations"]) for row in cards] == [
            (1, 1, 1)
        ] * 2

    with TestClient(create_app(settings, embed_model=MockEmbedding(embed_dim=2))) as client:
        assert len(client.get("/api/assistants").json()) == 2
        assert (
            client.get(f"{a_base}/sessions/{a_session}").json()["turns"][0]["answer"]
            == "HR policy: 30 days"
        )
        assert client.get(f"{a_base}/files/{a_file}/download").content == b"HR policy: 30 days"
        assert (
            client.put(a_base, json={"name": "السياسات", "instructions": "رد بنقاط"}).status_code
            == 200
        )
        assert client.get(a_base).json()["instructions"] == "رد بنقاط"
        assert client.delete(a_base).status_code == 204
        assert not (settings.web_data_dir / "assistants" / a["id"]).exists()
        assert client.get(a_base).status_code == 404
        assert client.get(a_base + "/files").status_code == 404
        assert client.get(b_base).json()["files"] == 1
        assert client.get(f"{b_base}/sessions/{b_session}").status_code == 200

    with TestClient(create_app(settings, embed_model=MockEmbedding(embed_dim=2))) as client:
        assert [row["id"] for row in client.get("/api/assistants").json()] == [b["id"]]


def test_shared_settings_apply_to_every_assistant_and_embedding_lock_checks_all(tmp_path):
    settings = web_settings(tmp_path)
    seen = []

    async def answer(question, *, settings, session_id, **kwargs):
        seen.append((settings.agent_model, settings.assistant_instructions))
        return {"answer": "ok", "sources": [], "session_id": session_id}

    with TestClient(
        create_app(settings, embed_model=MockEmbedding(embed_dim=2), answer=answer)
    ) as client:
        _, a = create(client, instructions="مختصر")
        _, b = create(client, "المالية", instructions="مفصل")
        assert client.put("/api/settings", json={"agent_model": "gpt-4o-mini"}).status_code == 200
        for base in (a, b):
            session = client.post(base + "/sessions").json()["session_id"]
            assert (
                client.post(
                    f"{base}/sessions/{session}/messages", json={"question": "Hi"}
                ).status_code
                == 200
            )
        file_id = train(client, b, "Finance")
        assert client.get("/api/settings").json()["embedding_locked"]
        assert client.put("/api/settings", json={"embedding_model": "different"}).status_code == 409
        assert client.post(f"{b}/files/{file_id}/unindex").status_code == 200
        assert not client.get("/api/settings").json()["embedding_locked"]
        assert client.put("/api/settings", json={"embedding_model": "different"}).status_code == 200
    assert seen == [("gpt-4o-mini", "مختصر"), ("gpt-4o-mini", "مفصل")]


def test_delete_cancels_training_and_recovers_interrupted_deletion(tmp_path):
    settings = web_settings(tmp_path)

    async def prepare(resource, settings, progress):
        await asyncio.sleep(30)
        return [TextNode(text="unfinished")]

    app = create_app(settings, prepare=prepare)
    with TestClient(app) as client:
        row, base = create(client)
        file = client.post(base + "/files", files={"file": ("notes.txt", b"notes")}).json()
        assert client.post(f"{base}/files/{file['id']}/train").status_code == 202
        assert client.delete(base).status_code == 204
        assert client.get("/api/assistants").json() == []
        assert not (settings.web_data_dir / "assistants" / row["id"]).exists()
        pending, pending_base = create(client)
        client.post(pending_base + "/sessions")
        # Persisted deletion intent survives a process ending before directory removal.
        app.state.assistants.begin_delete(pending["id"])
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/assistants").json() == []
        assert not (settings.web_data_dir / "assistants" / pending["id"]).exists()


def test_delete_and_edit_wait_for_inflight_answers(tmp_path):
    started = threading.Event()
    release = threading.Event()

    async def answer(question, *, settings, session_id, **kwargs):
        started.set()
        while not release.is_set():
            await asyncio.sleep(0.01)
        session = load_session(session_id, settings=settings)
        session["turns"].append({"question": question, "answer": "saved", "sources": []})
        save_session(session, settings=settings)
        return {"answer": "saved", "sources": [], "session_id": session_id}

    with TestClient(create_app(web_settings(tmp_path), answer=answer)) as client:
        _, base = create(client)
        session = client.post(base + "/sessions").json()["session_id"]
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                client.post, f"{base}/sessions/{session}/messages", json={"question": "Hi"}
            )
            try:
                assert started.wait(3)
                assert client.delete(base).status_code == 409
                assert client.put(base, json={"name": "new"}).status_code == 409
                assert (
                    client.put("/api/settings", json={"agent_model": "different"}).status_code
                    == 409
                )
            finally:
                release.set()
            assert future.result(timeout=3).status_code == 200
        assert client.delete(base).status_code == 204


def test_assistant_validation_and_unknown_identity_never_create_a_workspace(tmp_path):
    with TestClient(create_app(web_settings(tmp_path))) as client:
        for payload in ({"name": " "}, {"name": "x" * 101}, {"name": "test", "unexpected": True}):
            assert client.post("/api/assistants", json=payload).status_code == 422
        row, base = create(client, "  المالية  ")
        assert row["name"] == "المالية"
        assert client.get("/api/assistants/not-a-uuid/files").status_code == 404
        assert client.delete("/api/assistants/not-a-uuid").status_code == 404
        assert client.get(base).status_code == 200
        assert len(client.get("/api/assistants").json()) == 1


def test_source_images_use_scoped_urls_and_remain_private_after_other_assistant_deletion(tmp_path):
    async def prepare(resource, settings, progress):
        image_id = str(uuid4())
        path = image_path(settings, image_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (8, 8), "green").save(path, "JPEG")
        return [
            TextNode(
                text="Original evidence",
                metadata={
                    "resource_id": resource["resource_id"],
                    "source": resource["file_name"],
                    "images": [{"id": image_id, "kind": "figure", "page_num": 1}],
                },
            )
        ]

    settings = web_settings(tmp_path)
    app = create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    with TestClient(app) as client:
        a, a_base = create(client)
        _, b_base = create(client, "المالية")
        train(client, a_base, "File A")
        b_file = train(client, b_base, "File B")
        nodes, _ = read_index_nodes(app.state.assistants.library(a["id"]).settings)
        chunk_id = nodes[0].node_id
        source = client.get(f"{a_base}/sources/{chunk_id}").json()
        url = source["images"][0]["url"]
        assert url.startswith(a_base + "/sources/")
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert client.get(url.replace(a_base, b_base)).status_code == 404
        assert client.get(url.replace(a_base, "/api")).status_code == 404
        assert client.delete(b_base).status_code == 204
        assert client.get(url).content == response.content
        assert client.delete(a_base).status_code == 204
        assert client.get(url).status_code == 404
        assert client.get(f"{b_base}/files/{b_file}/download").status_code == 404
