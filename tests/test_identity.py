"""Exercise ownership and session lifecycle through the public HTTP interface."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from pydantic import SecretStr

from advanced_rag import Settings
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.web.app import create_app
from advanced_rag.web.identity.providers import verify_supabase_token


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def settings_for(tmp_path):
    return Settings(
        _env_file=None,
        web_data_dir=tmp_path / "library",
        web_credential_encryption_key=SecretStr(Fernet.generate_key().decode()),
        openai_api_key=SecretStr("platform-key-must-not-leak"),
        llama_parse_api_key=SecretStr("platform-parse-key-must-not-leak"),
    )


@pytest.fixture
def accounts():
    users = {
        "account-a": {"id": str(uuid4()), "email": "a@example.com", "email_confirmed_at": "yes"},
        "account-b": {"id": str(uuid4()), "email": "b@example.com", "email_confirmed_at": "yes"},
        "unverified": {"id": str(uuid4()), "email": "unverified@example.com"},
    }

    async def verify(token):
        if token not in users:
            raise HTTPException(401, "Invalid sign-in")
        return users[token]

    return users, verify


def guest(client):
    response = client.post("/api/auth/guest")
    assert response.status_code == 201
    identity = response.json()
    return identity, {"X-Guest-Token": identity["token"]}


def account(token):
    return {"Authorization": "Bearer " + token}


def assistant(client, headers, name="private"):
    response = client.post("/api/assistants", json={"name": name}, headers=headers)
    assert response.status_code == 201
    return "/api/assistants/" + response.json()["id"]


def wait_until(predicate):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate()


def test_all_data_routes_require_a_real_principal(tmp_path, accounts):
    _, verify = accounts
    with TestClient(create_app(settings_for(tmp_path), identity_verifier=verify)) as client:
        assert client.get("/api/auth/config").json()["configured"] is False
        for path in (
            "/api/assistants",
            "/api/files",
            "/api/sessions",
            "/api/settings",
            "/api/health",
        ):
            assert client.get(path).status_code == 401
            assert client.get(path, headers={"X-User-ID": str(uuid4())}).status_code == 401
            assert client.get(path, headers=account("forged")).status_code == 401
            assert client.get(path, headers=account("unverified")).status_code == 401
        _, headers = guest(client)
        # A forged bearer must never fall back to a valid guest token.
        assert (
            client.get("/api/assistants", headers={**headers, **account("forged")}).status_code
            == 401
        )


def test_guests_accounts_media_and_compatibility_routes_are_isolated(tmp_path, accounts):
    _, verify = accounts

    async def prepare(resource, settings, progress):
        return [
            TextNode(
                text=resource["data"].decode(),
                metadata={"resource_id": resource["resource_id"], "source": "notes.txt"},
            )
        ]

    async def answer(question, *, context, settings, session_id, **kwargs):
        context = await context()
        node = context["nodes"][0]
        sources = [{"chunk_id": node.node_id, "citation": 1, "metadata": node.metadata}]
        session = load_session(session_id, settings=settings)
        session["turns"].append({"question": question, "answer": node.text, "sources": sources})
        save_session(session, settings=settings)
        return {"session_id": session_id, "answer": node.text, "sources": sources}

    with TestClient(
        create_app(
            settings_for(tmp_path),
            identity_verifier=verify,
            prepare=prepare,
            embed_model=MockEmbedding(embed_dim=2),
            answer=answer,
        )
    ) as client:
        a, a_headers = guest(client)
        _, b_headers = guest(client)
        a_base = assistant(client, a_headers)
        file = client.post(
            a_base + "/files", headers=a_headers, files={"file": ("notes.txt", b"guest-private")}
        ).json()
        assert (
            client.post(f"{a_base}/files/{file['id']}/train", headers=a_headers).status_code == 202
        )
        wait_until(
            lambda: (
                client.get(a_base + "/files", headers=a_headers).json()[0]["status"] == "trained"
            )
        )
        session_id = client.post(a_base + "/sessions", headers=a_headers).json()["session_id"]
        result = client.post(
            f"{a_base}/sessions/{session_id}/messages",
            headers=a_headers,
            json={"question": "contents?"},
        ).json()
        chunk_id = result["sources"][0]["chunk_id"]
        assert (
            client.get(f"{a_base}/files/{file['id']}/download", headers=a_headers).content
            == b"guest-private"
        )
        for other in (b_headers, account("account-a"), account("account-b")):
            for path in (
                a_base,
                a_base + "/files",
                f"{a_base}/files/{file['id']}/download",
                f"{a_base}/sessions/{session_id}",
                f"{a_base}/sources/{chunk_id}",
                f"{a_base}/sources/{chunk_id}/images/unknown",
            ):
                assert client.get(path, headers=other).status_code == 404
            assert client.delete(a_base, headers=other).status_code == 404
            assert (
                client.post(f"{a_base}/files/{file['id']}/train", headers=other).status_code == 404
            )
        # Unscoped compatibility APIs are still scoped to the current owner.
        assert client.get("/api/files", headers=b_headers).json() == []
        assert client.get(f"/api/files/{file['id']}/download", headers=b_headers).status_code == 404
        assert client.get("/api/assistants", headers=account("account-a")).json() == []
        assert client.post("/api/auth/guest/end", json={"token": a["token"]}).status_code == 202
        assert client.get(a_base, headers=a_headers).status_code == 401
        assert client.get("/api/assistants", headers=account("account-a")).json() == []


def test_owner_keys_are_encrypted_isolated_persistent_and_not_inherited(tmp_path, accounts):
    users, verify = accounts
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, identity_verifier=verify)) as client:
        a_base = assistant(client, account("account-a"))
        for headers in (account("account-a"), account("account-b"), guest(client)[1]):
            public = client.get("/api/settings", headers=headers).json()
            assert not public["openai_key_configured"]
            assert not public["llamaparse_key_configured"]
        response = client.put(
            "/api/settings",
            headers=account("account-a"),
            json={
                "openai_api_key": "a-private-key",
                "llama_parse_api_key": "a-parser-key",
                "agent_model": "custom-model",
                "embedding_model": "custom-embedding",
            },
        )
        assert response.status_code == 200
        assert "private-key" not in response.text
        assert not client.get("/api/settings", headers=account("account-b")).json()[
            "openai_key_configured"
        ]
        assert (
            client.get("/api/settings", headers=account("account-b")).json()["agent_model"]
            == settings.agent_model
        )
        directory = settings.web_data_dir / "owners" / "accounts" / users["account-a"]["id"]
        persisted = (directory / "settings.json").read_text()
        assert "a-private-key" not in persisted
        assert '"cipher": "fernet"' in persisted
    with TestClient(create_app(settings, identity_verifier=verify)) as client:
        assert client.get(a_base, headers=account("account-a")).status_code == 200
        public = client.get("/api/settings", headers=account("account-a")).json()
        assert public["openai_key_configured"] and public["agent_model"] == "custom-model"
        assert client.get("/api/assistants", headers=account("account-b")).json() == []


def test_renewal_uses_server_deadlines_and_reload_does_not_extend_them(tmp_path):
    clock = Clock()
    with TestClient(create_app(settings_for(tmp_path), clock=clock)) as client:
        row, headers = guest(client)
        assert row["renew_at"] == 1900
        assert row["expires_at"] == 1960
        base = assistant(client, headers)
        assert client.post("/api/auth/guest/renew", headers=headers).status_code == 409
        client.post("/api/auth/guest/closing", json={"token": row["token"]})
        clock.now += 5
        assert client.post("/api/auth/guest/resume", headers=headers).json()["renew_at"] == 1900
        assert client.get(base, headers=headers).status_code == 200
        clock.now = 1900
        renewed = client.post("/api/auth/guest/renew", headers=headers).json()
        assert renewed["renew_at"] == 2800 and renewed["expires_at"] == 2860
        clock.now = 2860
        assert client.get(base, headers=headers).status_code == 401
        assert client.post("/api/auth/guest/renew", headers=headers).status_code == 401


def test_closed_or_expired_guests_are_purged_including_settings(tmp_path):
    clock = Clock()
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, clock=clock)) as client:
        row, headers = guest(client)
        assistant(client, headers)
        client.put("/api/settings", headers=headers, json={"openai_api_key": "guest-secret"})
        directory = settings.web_data_dir / "owners" / "guests" / row["id"]
        assert directory.exists()
        client.post("/api/auth/guest/closing", json={"token": row["token"]})
        clock.now += settings.guest_close_grace_seconds
        assert client.get("/api/assistants", headers=headers).status_code == 401
        wait_until(lambda: not directory.exists())
        assert client.post("/api/auth/guest/resume", headers=headers).status_code == 401
        assert client.post("/api/auth/guest/end", json={"token": row["token"]}).status_code == 202
        new, new_headers = guest(client)
        assert new["id"] != row["id"]
        assert client.get("/api/assistants", headers=new_headers).json() == []
        assert not client.get("/api/settings", headers=new_headers).json()["openai_key_configured"]


def test_expiry_cancels_training_and_never_recreates_deleted_files(tmp_path):
    clock = Clock()
    started = []
    stopped = []

    async def prepare(resource, settings, progress):
        started.append(True)
        try:
            await asyncio.sleep(30)
        finally:
            stopped.append(True)
        return [TextNode(text="never publish")]

    settings = settings_for(tmp_path)
    with TestClient(
        create_app(settings, clock=clock, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        row, headers = guest(client)
        base = assistant(client, headers)
        file = client.post(
            base + "/files", headers=headers, files={"file": ("notes.txt", b"notes")}
        ).json()
        client.post(f"{base}/files/{file['id']}/train", headers=headers)
        wait_until(lambda: bool(started))
        clock.now = row["expires_at"]
        assert client.get(base, headers=headers).status_code == 401
        directory = settings.web_data_dir / "owners" / "guests" / row["id"]
        wait_until(lambda: bool(stopped) and not directory.exists())
        assert client.get(base, headers=headers).status_code == 401
        assert not directory.exists()


def test_expiry_interrupts_an_inflight_answer_before_cleanup(tmp_path):
    clock = Clock()
    started = []

    async def answer(*args, **kwargs):
        started.append(True)
        await asyncio.sleep(30)

    with TestClient(create_app(settings_for(tmp_path), clock=clock, answer=answer)) as client:
        row, headers = guest(client)
        base = assistant(client, headers)
        session_id = client.post(base + "/sessions", headers=headers).json()["session_id"]
        with ThreadPoolExecutor() as pool:
            pending = pool.submit(
                client.post,
                f"{base}/sessions/{session_id}/messages",
                headers=headers,
                json={"question": "hello"},
            )
            wait_until(lambda: bool(started))
            client.post("/api/auth/guest/end", json={"token": row["token"]})
            assert pending.result(timeout=5).status_code == 401
        directory = settings_for(tmp_path).web_data_dir / "owners" / "guests" / row["id"]
        wait_until(lambda: not directory.exists())


def test_expired_guest_cleanup_recovers_after_server_restart(tmp_path):
    clock = Clock()
    settings = settings_for(tmp_path)
    with TestClient(create_app(settings, clock=clock)) as client:
        row, headers = guest(client)
        assistant(client, headers)
    directory = settings.web_data_dir / "owners" / "guests" / row["id"]
    assert directory.exists()
    clock.now = row["expires_at"]
    with TestClient(create_app(settings, clock=clock)) as client:
        assert client.get("/api/assistants", headers=headers).status_code == 401
        wait_until(lambda: not directory.exists())


def test_missing_provider_keys_fail_before_starting_a_job_or_title(tmp_path):
    with TestClient(
        create_app(settings_for(tmp_path), embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        _, headers = guest(client)
        base = assistant(client, headers)
        file = client.post(
            base + "/files", headers=headers, files={"file": ("document.pdf", b"%PDF-1.7\n")}
        ).json()
        response = client.post(f"{base}/files/{file['id']}/train", headers=headers)
        assert response.status_code == 400 and "OpenAI" in response.json()["detail"]
        client.put("/api/settings", headers=headers, json={"openai_api_key": "own-key"})
        response = client.post(f"{base}/files/{file['id']}/train", headers=headers)
        assert response.status_code == 400 and "LlamaParse" in response.json()["detail"]
        assert client.get(base + "/files", headers=headers).json()[0]["status"] == "untrained"
        client.put("/api/settings", headers=headers, json={"openai_api_key": ""})
        session_id = client.post(base + "/sessions", headers=headers).json()["session_id"]
        response = client.post(
            f"{base}/sessions/{session_id}/messages", headers=headers, json={"question": "hello"}
        )
        assert response.status_code == 400 and "OpenAI" in response.json()["detail"]
        session = client.get(f"{base}/sessions/{session_id}", headers=headers).json()
        assert session["turns"] == [] and session["title_status"] == "idle"


def test_real_verifier_checks_auth_service_and_fails_closed(tmp_path):
    settings = settings_for(tmp_path).model_copy(
        update={
            "supabase_url": "https://example.supabase.co",
            "supabase_publishable_key": "sb_publishable_test",
        }
    )

    async def exercise():
        calls = []

        def handler(request):
            calls.append(request)
            assert request.url.path == "/auth/v1/user"
            assert request.headers["apikey"] == "sb_publishable_test"
            assert request.headers["authorization"] == "Bearer signed-token"
            return httpx.Response(401)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(HTTPException) as failure:
                await verify_supabase_token(settings, client, "signed-token")
            assert failure.value.status_code == 401 and len(calls) == 1

    asyncio.run(exercise())


def test_secret_supabase_key_is_never_exposed_as_public_config(tmp_path):
    settings = settings_for(tmp_path).model_copy(
        update={
            "supabase_publishable_key": "sb_secret_private-key",
            "supabase_url": "https://example.supabase.co",
        }
    )
    with pytest.raises(ValueError, match="publishable/anon"):
        create_app(settings)


def test_busy_and_embedding_checks_apply_only_to_the_owner(tmp_path, accounts):
    _, verify = accounts
    started = []
    release = []

    async def prepare(resource, settings, progress):
        started.append(True)
        while not release:
            await asyncio.sleep(0.01)
        return [TextNode(text="notes", metadata={"resource_id": resource["resource_id"]})]

    with TestClient(
        create_app(
            settings_for(tmp_path),
            identity_verifier=verify,
            prepare=prepare,
            embed_model=MockEmbedding(embed_dim=2),
        )
    ) as client:
        a_headers, b_headers = account("account-a"), account("account-b")
        a_base = assistant(client, a_headers)
        assistant(client, b_headers)
        file = client.post(
            a_base + "/files", headers=a_headers, files={"file": ("notes.txt", b"notes")}
        ).json()
        client.post(f"{a_base}/files/{file['id']}/train", headers=a_headers)
        wait_until(lambda: bool(started))
        assert (
            client.put(
                "/api/settings", headers=a_headers, json={"agent_model": "another-model"}
            ).status_code
            == 409
        )
        assert (
            client.put(
                "/api/settings", headers=b_headers, json={"agent_model": "b-model"}
            ).status_code
            == 200
        )
        release.append(True)
        wait_until(
            lambda: (
                client.get(a_base + "/files", headers=a_headers).json()[0]["status"] == "trained"
            )
        )
        assert (
            client.put(
                "/api/settings", headers=a_headers, json={"embedding_model": "new-embedding"}
            ).status_code
            == 409
        )
        assert (
            client.put(
                "/api/settings", headers=b_headers, json={"embedding_model": "new-embedding"}
            ).status_code
            == 200
        )
        assert (
            client.get("/api/settings", headers=a_headers).json()["embedding_model"]
            == "text-embedding-3-small"
        )
