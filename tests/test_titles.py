import asyncio
import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from conftest import api_client, response_payload
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_web import web_settings

from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.agent.titles import generate_title
from advanced_rag.web.app import create_app


def wait_for_title(client, session_id):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        saved = client.get(f"/api/sessions/{session_id}").json()
        if saved["title_status"] in ("ready", "error"):
            return saved
        time.sleep(0.01)
    raise AssertionError("Conversation title did not finish")


def test_title_service_failure_does_not_copy_the_first_message(tmp_path):
    question = "اشرح فوائد البنية المؤسسية"

    async def run():
        async with api_client(
            lambda request: httpx.Response(503, json={"error": {"message": "Unavailable"}})
        ) as client:
            return await generate_title(question, client=client, settings=web_settings(tmp_path))

    assert asyncio.run(run()) != question


@pytest.mark.parametrize("failure", [False, True])
def test_web_generates_title_once_and_preserves_it_after_restart(tmp_path, monkeypatch, failure):
    settings = web_settings(tmp_path).model_copy(
        update={"openai_api_key": SecretStr("test-key"), "title_model": "separate-title-model"}
    )
    title_requests = []
    answer_requests = []
    question = "اشرح لي كيف تعمل تقنية البحث في المستندات بالتفصيل"
    title = "تعذر تسمية المحادثة" if failure else "البحث في المستندات"

    def respond(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] == "conversation_title":
            title_requests.append(body)
            assert body["model"] == "separate-title-model"
            assert body["input"] == [{"role": "user", "content": question}]
            assert body["store"] is False
            if failure:
                return httpx.Response(503, json={"error": {"message": "Unavailable"}})
            return httpx.Response(200, json=response_payload({"title": title}))
        answer_requests.append(body)
        return httpx.Response(
            200, json=response_payload({"answer": "إجابة المحادثة", "cited_chunk_ids": []})
        )

    monkeypatch.setattr("advanced_rag.web.app.AsyncOpenAI", lambda **kwargs: api_client(respond))
    with TestClient(create_app(settings)) as client:
        session = client.post("/api/sessions").json()
        assert session["title"] == "محادثة جديدة"
        session_id = session["session_id"]
        result = client.post(f"/api/sessions/{session_id}/messages", json={"question": question})
        assert result.status_code == 200
        assert result.json()["answer"] == "إجابة المحادثة"
        assert wait_for_title(client, session_id)["title"] == title
        assert client.get(f"/api/sessions/{session_id}").json()["title_status"] == (
            "error" if failure else "ready"
        )
        assert client.get("/api/sessions").json()[0]["title"] == title
    with TestClient(create_app(settings)) as client:
        assert client.get(f"/api/sessions/{session_id}").json()["title"] == title
        result = client.post(f"/api/sessions/{session_id}/messages", json={"question": "وضح أكثر"})
        assert result.json()["title"] == title
        assert len(client.get(f"/api/sessions/{session_id}").json()["turns"]) == 2
    assert len(title_requests) == 1
    assert len(answer_requests) == 2


@pytest.mark.parametrize(
    "data,status",
    [
        ({"title": ""}, "completed"),
        ({"title": 5}, "completed"),
        ({}, "completed"),
        ({"title": "عنوان"}, "incomplete"),
    ],
)
def test_invalid_title_signals_failure_without_copying_message(tmp_path, data, status):
    payload = response_payload(data)
    payload["status"] = status

    async def run():
        async with api_client(lambda request: httpx.Response(200, json=payload)) as client:
            return await generate_title("أول رسالة", client=client, settings=web_settings(tmp_path))

    assert asyncio.run(run()) is None


def test_title_timeout_signals_failure_without_copying_message(tmp_path):
    async def create(**kwargs):
        raise TimeoutError

    client = SimpleNamespace(responses=SimpleNamespace(create=create))
    assert (
        asyncio.run(generate_title("أول رسالة", client=client, settings=web_settings(tmp_path)))
        is None
    )


def test_old_sessions_without_titles_remain_readable(tmp_path):
    settings = web_settings(tmp_path)
    session = load_session(None, settings=settings)
    session.pop("title")
    session["turns"].append({"question": "Old question", "answer": "Old answer", "sources": []})
    save_session(session, settings=settings)
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/sessions").json()[0]["title"] == "Old question"
        assert (
            client.get(f"/api/sessions/{session['session_id']}").json()["title"] == "Old question"
        )


def test_failed_answer_does_not_cancel_independent_title(tmp_path, monkeypatch):
    settings = web_settings(tmp_path).model_copy(update={"openai_api_key": SecretStr("test-key")})

    def respond(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] == "conversation_title":
            return httpx.Response(200, json=response_payload({"title": "Generated title"}))
        return httpx.Response(503, json={"error": {"message": "Unavailable"}})

    monkeypatch.setattr("advanced_rag.web.app.AsyncOpenAI", lambda **kwargs: api_client(respond))
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        assert (
            client.post(
                f"/api/sessions/{session_id}/messages", json={"question": "First message"}
            ).status_code
            == 502
        )
        saved = wait_for_title(client, session_id)
        assert saved["turns"] == []
        assert saved["title"] == "Generated title"


@pytest.mark.parametrize("slow_operation", ["answer", "title"])
def test_title_and_answer_are_published_independently(tmp_path, monkeypatch, slow_operation):
    settings = web_settings(tmp_path).model_copy(update={"openai_api_key": SecretStr("test-key")})
    started = threading.Event()
    release = threading.Event()
    title_calls = []

    async def respond(request):
        body = json.loads(request.content)
        is_title = body["text"]["format"]["name"] == "conversation_title"
        operation = "title" if is_title else "answer"
        if is_title:
            title_calls.append(body)
        if operation == slow_operation:
            started.set()
            while not release.is_set():
                await asyncio.sleep(0.005)
        return httpx.Response(
            200,
            json=response_payload(
                {"title": "Independent title"}
                if is_title
                else {"answer": "Independent answer", "cited_chunk_ids": []}
            ),
        )

    monkeypatch.setattr("advanced_rag.web.app.AsyncOpenAI", lambda **kwargs: api_client(respond))
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        responses = []
        request_thread = threading.Thread(
            target=lambda: responses.append(
                client.post(
                    f"/api/sessions/{session_id}/messages", json={"question": "First message"}
                )
            )
        )
        request_thread.start()
        try:
            assert started.wait(timeout=3)
            if slow_operation == "answer":
                saved = wait_for_title(client, session_id)
                assert saved["title"] == "Independent title"
                assert saved["turns"] == []
                assert request_thread.is_alive()
                assert client.get("/api/sessions").json()[0]["title"] == "Independent title"
            else:
                request_thread.join(timeout=3)
                assert not request_thread.is_alive(), "Answer waited for title generation"
                assert responses[0].json()["answer"] == "Independent answer"
                assert responses[0].json()["title_status"] == "pending"
                summary = client.get("/api/sessions").json()[0]
                assert summary["title_status"] == "pending"
                assert summary["turns"] == 1
                # A follow-up can be answered without restarting or waiting for the title.
                followup = client.post(
                    f"/api/sessions/{session_id}/messages", json={"question": "Follow-up"}
                )
                assert followup.status_code == 200
        finally:
            release.set()
            request_thread.join(timeout=3)
        assert responses[0].status_code == 200
        saved = wait_for_title(client, session_id)
        assert saved["title"] == "Independent title"
        assert len(saved["turns"]) == (1 if slow_operation == "answer" else 2)
        assert len(title_calls) == 1


def test_pending_title_is_resumed_after_process_restart(tmp_path, monkeypatch):
    settings = web_settings(tmp_path)
    saved = load_session(None, settings=settings)
    saved["title_status"] = "pending"
    saved["title_question"] = "Original first message"
    save_session(saved, settings=settings)
    questions = []

    async def title(question, **kwargs):
        questions.append(question)
        return "Recovered title"

    monkeypatch.setattr("advanced_rag.web.app.generate_title", title)

    async def answer(*args, **kwargs):
        raise AssertionError("Title recovery must not generate a chat answer")

    with TestClient(create_app(settings, answer=answer)) as client:
        assert wait_for_title(client, saved["session_id"])["title"] == "Recovered title"
    assert questions == ["Original first message"]


def test_reasoning_budget_allows_a_real_title(tmp_path):
    def respond(request):
        body = json.loads(request.content)
        payload = response_payload({"title": "فوائد البنية المؤسسية"})
        if body["max_output_tokens"] < 1024:
            payload["status"] = "incomplete"
            payload["incomplete_details"] = {"reason": "max_output_tokens"}
            payload["output"] = []
        return httpx.Response(200, json=payload)

    async def run():
        async with api_client(respond) as client:
            return await generate_title(
                "اشرح فوائد البنية المؤسسية", client=client, settings=web_settings(tmp_path)
            )

    assert asyncio.run(run()) == "فوائد البنية المؤسسية"


def test_retry_title_uses_first_message_without_resending_answer(tmp_path, monkeypatch):
    settings = web_settings(tmp_path).model_copy(update={"openai_api_key": SecretStr("test-key")})
    title_calls = []
    answer_calls = []
    question = "Explain the benefits of enterprise architecture"

    def respond(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] == "conversation_title":
            title_calls.append(body)
            if len(title_calls) == 1:
                return httpx.Response(400, json={"error": {"message": "Invalid request"}})
            assert body["input"] == [{"role": "user", "content": question}]
            return httpx.Response(
                200, json=response_payload({"title": "Enterprise architecture benefits"})
            )
        answer_calls.append(body)
        return httpx.Response(
            200, json=response_payload({"answer": "Saved answer", "cited_chunk_ids": []})
        )

    monkeypatch.setattr("advanced_rag.web.app.AsyncOpenAI", lambda **kwargs: api_client(respond))
    with TestClient(create_app(settings)) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        assert (
            client.post(
                f"/api/sessions/{session_id}/messages", json={"question": question}
            ).status_code
            == 200
        )
        failed = wait_for_title(client, session_id)
        assert failed["title_status"] == "error"
        assert failed["title"] != question
        assert client.post(f"/api/sessions/{session_id}/title").status_code == 202
        recovered = wait_for_title(client, session_id)
        assert recovered["title_status"] == "ready"
        assert recovered["title"] == "Enterprise architecture benefits"
        assert recovered["turns"] == failed["turns"]
    assert len(answer_calls) == 1
    assert len(title_calls) == 2
