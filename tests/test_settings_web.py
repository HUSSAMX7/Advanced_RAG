import asyncio

from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from test_web import wait_status, web_settings

from advanced_rag.storage import load_faiss_index
from advanced_rag.web.app import create_app


def test_saved_settings_are_applied_and_keys_are_protected_after_restart(tmp_path):
    settings = web_settings(tmp_path)
    seen = []

    async def answer(question, *, settings, **kwargs):
        seen.append((settings.agent_model, settings.openai_api_key.get_secret_value()))
        return {"answer": "ok", "sources": [], "session_id": kwargs["session_id"]}

    with TestClient(create_app(settings, answer=answer)) as client:
        saved = client.put(
            "/api/settings",
            json={
                "pdf_provider": "lightonocr",
                "agent_model": "gpt-4o",
                "openai_api_key": "private-openai-key",
                "llama_parse_api_key": "private-parse-key",
            },
        )
        assert saved.status_code == 200
        assert saved.json()["openai_key_configured"] is True
        assert "private" not in saved.text
        session = client.post("/api/sessions").json()
        assert (
            client.post(
                f"/api/sessions/{session['session_id']}/messages", json={"question": "hi"}
            ).status_code
            == 200
        )
    persisted = (settings.web_data_dir / "settings.json").read_text()
    assert "private" not in persisted
    with TestClient(create_app(settings, answer=answer)) as client:
        current = client.get("/api/settings").json()
        assert current["pdf_provider"] == "lightonocr"
        assert current["agent_model"] == "gpt-4o"
        session = client.post("/api/sessions").json()
        client.post(f"/api/sessions/{session['session_id']}/messages", json={"question": "hi"})
    assert seen == [("gpt-4o", "private-openai-key")] * 2


def test_empty_secret_removes_it_and_omission_retains_it(tmp_path):
    from pydantic import SecretStr

    baseline = web_settings(tmp_path).model_copy(update={"openai_api_key": SecretStr("env-key")})
    with TestClient(create_app(baseline)) as client:
        client.put("/api/settings", json={"openai_api_key": "retained-key"})
        assert client.put("/api/settings", json={"agent_model": "gpt-4o"}).json()[
            "openai_key_configured"
        ]
        assert not client.put("/api/settings", json={"openai_api_key": ""}).json()[
            "openai_key_configured"
        ]
    with TestClient(create_app(baseline)) as client:
        assert not client.get("/api/settings").json()["openai_key_configured"]


def test_embedding_change_is_blocked_until_indexing_is_removed(tmp_path):
    settings = web_settings(tmp_path)
    with TestClient(create_app(settings, embed_model=MockEmbedding(embed_dim=2))) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"notes")}).json()
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
        assert (
            client.put(
                "/api/settings", json={"embedding_model": "text-embedding-3-large"}
            ).status_code
            == 409
        )
        assert client.get("/api/settings").json()["embedding_model"] == settings.embedding_model
        client.post(f"/api/files/{row['id']}/unindex")
        assert (
            client.put(
                "/api/settings", json={"embedding_model": "text-embedding-3-large"}
            ).status_code
            == 200
        )

    with TestClient(create_app(settings, embed_model=MockEmbedding(embed_dim=3))) as client:
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
        assert client.get(f"/api/files/{row['id']}/download").content == b"notes"
        index = load_faiss_index(settings, embed_model=MockEmbedding(embed_dim=3))
        assert index.vector_store.client.d == 3
        assert index.vector_store.client.ntotal == 1


def test_settings_save_is_rejected_while_training_runs(tmp_path):
    async def prepare(resource, settings, progress):
        await asyncio.sleep(10)
        return [TextNode(text="notes")]

    with TestClient(create_app(web_settings(tmp_path), prepare=prepare)) as client:
        row = client.post("/api/files", files={"file": ("notes.txt", b"notes")}).json()
        client.post(f"/api/files/{row['id']}/train")
        assert client.put("/api/settings", json={"pdf_provider": "lightonocr"}).status_code == 409
        client.post(f"/api/files/{row['id']}/cancel")


def test_bad_settings_never_echo_secret_input(tmp_path):
    with TestClient(create_app(web_settings(tmp_path))) as client:
        response = client.put("/api/settings", json={"openai_api_key": "private-secret" * 1000})
        assert response.status_code == 422
        assert "private-secret" not in response.text
        assert (
            client.put("/api/settings", json={"faiss_persist_dir": "elsewhere"}).status_code == 422
        )
        assert client.put("/api/settings", json={"agent_model": "   "}).status_code == 422


def test_training_receives_saved_provider_and_credentials(tmp_path):
    seen = []

    async def prepare(resource, settings, progress):
        progress("preparing_ocr")
        progress("ocr_page:1:1")
        seen.append(
            (
                settings.pdf_provider,
                settings.lightonocr_local,
                settings.openai_api_key.get_secret_value(),
            )
        )
        return [TextNode(text="notes", metadata={"resource_id": resource["resource_id"]})]

    with TestClient(
        create_app(web_settings(tmp_path), prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        client.put(
            "/api/settings", json={"pdf_provider": "lightonocr", "openai_api_key": "saved-key"}
        )
        row = client.post("/api/files", files={"file": ("notes.pdf", b"%PDF-1.7\n")}).json()
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
    assert seen == [("lightonocr", True, "saved-key")]
