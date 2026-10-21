"""Storage failures, owner isolation and cache recovery across the HTTP boundary."""

import asyncio
import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from pydantic import SecretStr
from test_web import wait_status, web_settings

from advanced_rag import Settings
from advanced_rag.web.app import create_app
from advanced_rag.web.files import object_storage


@pytest.fixture
def remote(monkeypatch):
    objects = {}
    state = {"objects": objects, "fail": False, "public": False, "calls": []}

    def handle(request):
        assert request.headers["apikey"] == "private-test-key"
        state["calls"].append(request)
        if state["fail"]:
            return httpx.Response(500, json={"message": "private-test-key"})
        path = request.url.path
        if "/bucket/" in path:
            return httpx.Response(200, json={"public": state["public"]})
        if "/object/authenticated/documents/" in path:
            key = path.split("/documents/", 1)[1]
            return httpx.Response(200, content=objects[key])
        if "/object/list/" in path:
            import json

            prefix = json.loads(request.content)["prefix"]
            children = {}
            for key in objects:
                if key.startswith(prefix):
                    tail = key[len(prefix) :]
                    name, slash, _ = tail.partition("/")
                    children[name] = {"name": name, "id": None if slash else key}
            return httpx.Response(200, json=list(children.values())[:100])
        if request.method == "POST":
            key = path.split("/documents/", 1)[1]
            objects[key] = request.content
            return httpx.Response(200, json={"Key": key})
        if request.method == "DELETE":
            import json

            for key in json.loads(request.content)["prefixes"]:
                objects.pop(key, None)
            return httpx.Response(200, json=[])
        raise AssertionError(str(request.url))

    monkeypatch.setattr(
        object_storage,
        "client",
        lambda settings: httpx.Client(
            base_url="https://example.supabase.co/storage/v1/",
            headers={"apikey": settings.rag_supabase_secret_key.get_secret_value()},
            transport=httpx.MockTransport(handle),
        ),
    )
    return state


def cloud_settings(tmp_path):
    return web_settings(tmp_path).model_copy(
        update={
            "rag_supabase_url": "https://example.supabase.co",
            "rag_supabase_secret_key": SecretStr("private-test-key"),
        }
    )


def test_upload_cache_loss_train_unindex_and_delete(tmp_path, remote):
    settings = cloud_settings(tmp_path)
    with TestClient(create_app(settings, embed_model=MockEmbedding(embed_dim=2))) as client:
        response = client.post("/api/files", files={"file": ("notes.txt", b"cloud document")})
        assert response.status_code == 201
        file_id = response.json()["id"]
        assert list(remote["objects"].values()) == [b"cloud document"]
        for path in (settings.web_data_dir / "uploads").iterdir():
            path.unlink()
        assert client.get(f"/api/files/{file_id}/download").content == b"cloud document"
        for path in (settings.web_data_dir / "uploads").iterdir():
            path.unlink()
        assert client.post(f"/api/files/{file_id}/train").status_code == 202
        wait_status(client, file_id, "trained")
        assert client.post(f"/api/files/{file_id}/unindex").status_code == 200
        assert len(remote["objects"]) == 1
        assert client.delete(f"/api/files/{file_id}").status_code == 204
        assert remote["objects"] == {}


def test_failed_upload_leaves_no_record_or_local_original(tmp_path, remote):
    settings = cloud_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        remote["fail"] = True
        response = client.post("/api/files", files={"file": ("notes.txt", b"notes")})
        assert response.status_code == 503
        assert "private-test-key" not in response.text
        assert client.get("/api/files").json() == []
        assert list((settings.web_data_dir / "uploads").iterdir()) == []


def test_failed_delete_keeps_intent_and_retries_after_restart(tmp_path, remote):
    settings = cloud_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        file_id = client.post("/api/files", files={"file": ("a.txt", b"notes")}).json()["id"]
        remote["fail"] = True
        assert client.delete(f"/api/files/{file_id}").status_code == 503
        assert len(client.get("/api/files").json()) == 1
        assert remote["objects"]
    remote["fail"] = False
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/files").json() == []
        assert remote["objects"] == {}


def test_assistant_deletion_cleans_only_its_prefix_with_multiple_batches(tmp_path, remote):
    settings = cloud_settings(tmp_path)
    with TestClient(create_app(settings)) as client:
        first = client.post("/api/assistants", json={"name": "one"}).json()["id"]
        second = client.post("/api/assistants", json={"name": "two"}).json()["id"]
        for assistant_id in (first, second):
            response = client.post(
                f"/api/assistants/{assistant_id}/files", files={"file": ("a.txt", b"notes")}
            )
            assert response.status_code == 201
        for i in range(105):
            remote["objects"][f"local/assistants/{first}/uploads/orphan-{i}"] = b"orphan"
        assert client.delete(f"/api/assistants/{first}").status_code == 204
        assert len(remote["objects"]) == 1
        assert next(iter(remote["objects"])).startswith(f"local/assistants/{second}/")


def test_public_bucket_is_rejected(tmp_path, remote):
    remote["public"] = True
    with (
        pytest.raises(object_storage.StorageUnavailable, match="خاصة"),
        TestClient(create_app(cloud_settings(tmp_path))),
    ):
        pass


def test_rag_upload_limit_alias_and_secret_redaction(monkeypatch):
    monkeypatch.setenv("RAG_MAX_UPLOAD_BYTES", "20971520")
    settings = Settings(_env_file=None, rag_supabase_secret_key="private-test-key")
    assert settings.max_upload_bytes == 20971520
    assert "private-test-key" not in repr(settings)


@pytest.mark.parametrize("original", ["../other.txt", "folder/file.txt", "..", "a\\b.txt"])
def test_object_names_cannot_escape_namespace(tmp_path, original):
    with pytest.raises(ValueError):
        object_storage.object_key(cloud_settings(tmp_path), original)


def test_guest_cleanup_keeps_account_originals_and_api_does_not_leak_secret(tmp_path, remote):
    settings = cloud_settings(tmp_path).model_copy(update={"web_identity_enabled": True})

    async def verify(token):
        return {
            "id": "11111111-1111-4111-8111-111111111111",
            "email": "account@example.com",
            "email_confirmed_at": "yes",
        }

    with TestClient(create_app(settings, identity_verifier=verify)) as client:
        guest = client.post("/api/auth/guest").json()
        guest_headers = {"X-Guest-Token": guest["token"]}
        account_headers = {"Authorization": "Bearer account"}
        for headers in (guest_headers, account_headers):
            response = client.post(
                "/api/files", files={"file": ("a.txt", b"notes")}, headers=headers
            )
            assert response.status_code == 201
        assert "private-test-key" not in client.get("/api/auth/config").text
        assert any(key.startswith("owners/guests/") for key in remote["objects"])
        assert any(key.startswith("owners/accounts/") for key in remote["objects"])
        assert client.post("/api/auth/guest/end", json={"token": guest["token"]}).status_code == 202
        deadline = time.monotonic() + 5
        while any(key.startswith("owners/guests/") for key in remote["objects"]):
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert len(remote["objects"]) == 1
        assert next(iter(remote["objects"])).startswith("owners/accounts/")


def test_cancellation_drains_storage_before_owner_cleanup():
    started = threading.Event()
    release = threading.Event()

    def operation():
        started.set()
        release.wait(5)

    async def scenario():
        task = asyncio.create_task(object_storage.run(operation))
        while not started.is_set():
            await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0.01)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task

    try:
        asyncio.run(scenario())
    finally:
        release.set()
