import asyncio
import json

import httpx
import pytest
from conftest import api_client, response_payload
from openai import BadRequestError

from advanced_rag.agent import ask_agent
from advanced_rag.agent.memory import MemoryContextError
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.retrieval import load_search_context


def overflow():
    return httpx.Response(
        400,
        json={"error": {"message": "Input exceeds context", "code": "context_length_exceeded"}},
    )


def saved_history(settings, count=12):
    session = load_session(None, settings=settings)
    session["turns"] = [
        {"question": f"Earlier {i}", "answer": f"Answer {i} ZX-774", "sources": []}
        for i in range(count)
    ]
    save_session(session, settings=settings)
    return session


def run_question(settings, session, handler, *, context=None, question="Follow up"):
    async def run():
        async with api_client(handler) as client:
            return await ask_agent(
                question,
                context=context,
                client=client,
                settings=settings,
                session_id=session["session_id"],
            )

    return asyncio.run(run())


def summary_response(summary="Earlier 0 and 1: invoice ZX-774"):
    return httpx.Response(200, json=response_payload({"summary": summary}))


def answer_response():
    return httpx.Response(200, json=response_payload({"answer": "Done", "cited_chunk_ids": []}))


def test_overflow_compacts_old_turns_and_reuses_saved_memory_without_changing_history(corpus):
    settings, _ = corpus
    session = saved_history(settings)
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        assert body["store"] is False
        assert body["truncation"] == "disabled"
        if len(bodies) == 1:
            assert len(body["input"]) == 25
            return overflow()
        if body["text"]["format"]["name"] == "conversation_memory":
            fragment = json.loads(body["input"][0]["content"])
            assert fragment["previous_summary"] == ""
            assert "Earlier 0" in fragment["conversation_fragment"]
            assert "Earlier 1" in fragment["conversation_fragment"]
            assert "Earlier 2" not in fragment["conversation_fragment"]
            return summary_response()
        assert json.loads(body["input"][0]["content"])["summarized_turns"] == 2
        assert [item["content"] for item in body["input"] if item["role"] == "user"] == [
            *(f"Earlier {i}" for i in range(2, 12)),
            "Follow up",
        ]
        return answer_response()

    result = run_question(settings, session, respond)
    assert len(bodies) == 3
    resumed = load_session(result["session_id"], settings=settings)
    assert resumed["turns"][:-1] == session["turns"]
    assert resumed["memory"] == {
        "summary": "Earlier 0 and 1: invoice ZX-774",
        "summarized_turns": 2,
    }

    next_bodies = []

    def resumed_response(request):
        body = json.loads(request.content)
        next_bodies.append(body)
        assert body["text"]["format"]["name"] == "chat_answer"
        assert (
            json.loads(body["input"][0]["content"])["conversation_history_summary"]
            == (resumed["memory"]["summary"])
        )
        assert [item["content"] for item in body["input"] if item["role"] == "user"] == [
            *(f"Earlier {i}" for i in range(2, 12)),
            "Follow up",
            "Next",
        ]
        return answer_response()

    run_question(settings, resumed, resumed_response, question="Next")
    assert len(next_bodies) == 1


def test_later_overflow_extends_existing_summary_only_with_newly_old_turns(corpus):
    settings, _ = corpus
    session = saved_history(settings, count=13)
    session["memory"] = {"summary": "Existing memory", "summarized_turns": 2}
    save_session(session, settings=settings)
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            return overflow()
        if body["text"]["format"]["name"] == "conversation_memory":
            fragment = json.loads(body["input"][0]["content"])
            assert fragment["previous_summary"] == "Existing memory"
            assert json.loads(fragment["conversation_fragment"]) == session["turns"][2]
            return summary_response("Extended memory with Earlier 2")
        assert json.loads(body["input"][0]["content"])["summarized_turns"] == 3
        assert body["input"][1] == {"role": "user", "content": "Earlier 3"}
        return answer_response()

    run_question(settings, session, respond)
    resumed = load_session(session["session_id"], settings=settings)
    assert resumed["memory"]["summarized_turns"] == 3
    assert resumed["turns"][:-1] == session["turns"]


def test_large_old_messages_are_summarized_in_adaptive_fragments_without_dropping_text(corpus):
    settings, _ = corpus
    session = saved_history(settings)
    session["turns"][0]["question"] = "تفصيل مهم ZX-774 " * 2000
    save_session(session, settings=settings)
    expected = "\n".join(json.dumps(turn, ensure_ascii=False) for turn in session["turns"][:2])
    accepted_fragments = []
    summary_requests = []
    chat_requests = []

    def respond(request):
        body = json.loads(request.content)
        if body["text"]["format"]["name"] == "conversation_memory":
            summary_requests.append(body)
            data = json.loads(body["input"][0]["content"])
            fragment = data["conversation_fragment"]
            assert len(fragment) <= 12000
            if len(summary_requests) == 1:
                return overflow()
            assert data["previous_summary"] == (
                f"Memory {len(accepted_fragments)}" if accepted_fragments else ""
            )
            accepted_fragments.append(fragment)
            return summary_response(f"Memory {len(accepted_fragments)}")
        chat_requests.append(body)
        return overflow() if len(chat_requests) == 1 else answer_response()

    run_question(settings, session, respond)
    assert "".join(accepted_fragments) == expected
    resumed = load_session(session["session_id"], settings=settings)
    assert resumed["turns"][:-1] == session["turns"]
    assert resumed["memory"]["summarized_turns"] == 2


def test_overflow_after_search_keeps_tool_result_and_does_not_repeat_search(corpus, monkeypatch):
    from advanced_rag.agent import chat

    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    session = saved_history(settings)
    searches = []
    original_search = chat.search_documents

    async def search(query, **kwargs):
        searches.append(query)
        return await original_search(query, **kwargs)

    monkeypatch.setattr(chat, "search_documents", search)
    bodies = []

    def respond(request):
        body = json.loads(request.content)
        bodies.append(body)
        if len(bodies) == 1:
            payload = response_payload({})
            payload["output"] = [
                {
                    "id": "fc_search",
                    "type": "function_call",
                    "name": "search_documents",
                    "call_id": "call_search",
                    "arguments": json.dumps({"query": "ZX-774"}),
                    "status": "completed",
                }
            ]
            return httpx.Response(200, json=payload)
        if len(bodies) == 2:
            return overflow()
        if body["text"]["format"]["name"] == "conversation_memory":
            return summary_response()
        assert body["tool_choice"] == "none"
        assert body["input"][-3:] == bodies[1]["input"][-3:]
        return httpx.Response(
            200,
            json=response_payload({"answer": "120 dollars [1]", "cited_chunk_ids": ["identifier"]}),
        )

    result = run_question(settings, session, respond, context=context)
    assert len(bodies) == 4
    assert searches == ["ZX-774"]
    assert result["sources"][0]["chunk_id"] == "identifier"
    resumed = load_session(session["session_id"], settings=settings)
    assert resumed["memory"]["summarized_turns"] == 2
    assert resumed["turns"][:-1] == session["turns"]


@pytest.mark.parametrize("failure", ["summary", "incomplete_summary", "answer", "still_overflow"])
def test_compaction_failure_does_not_change_saved_session(corpus, failure):
    settings, _ = corpus
    session = saved_history(settings)
    calls = []

    def respond(request):
        body = json.loads(request.content)
        calls.append(body)
        if len(calls) == 1:
            return overflow()
        if body["text"]["format"]["name"] == "conversation_memory":
            if failure == "incomplete_summary":
                payload = response_payload({"summary": "Incomplete"})
                payload["status"] = "incomplete"
                return httpx.Response(200, json=payload)
            return summary_response("") if failure == "summary" else summary_response()
        if failure == "still_overflow":
            return overflow()
        return httpx.Response(200, json=response_payload({"answer": "", "cited_chunk_ids": []}))

    with pytest.raises(RuntimeError):
        run_question(settings, session, respond)
    assert load_session(session["session_id"], settings=settings) == session


def test_non_context_api_error_does_not_trigger_summarization(corpus):
    settings, _ = corpus
    session = saved_history(settings)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(
            400, json={"error": {"message": "Bad model", "code": "model_not_found"}}
        )

    with pytest.raises(BadRequestError, match="Bad model"):
        run_question(settings, session, respond)
    assert len(calls) == 1
    assert load_session(session["session_id"], settings=settings) == session


def test_context_overflow_with_only_recent_turns_is_actionable_and_preserves_session(corpus):
    settings, _ = corpus
    session = saved_history(settings, count=10)
    calls = []

    def respond(request):
        calls.append(request)
        return overflow()

    with pytest.raises(MemoryContextError, match="سعة المودل"):
        run_question(settings, session, respond)
    assert len(calls) == 1
    assert load_session(session["session_id"], settings=settings) == session


@pytest.mark.parametrize(
    "memory",
    [
        None,
        {},
        {"summary": "", "summarized_turns": 1},
        {"summary": "x", "summarized_turns": True},
        {"summary": "x", "summarized_turns": 13},
    ],
)
def test_invalid_persisted_memory_is_rejected(corpus, memory):
    settings, _ = corpus
    session = saved_history(settings)
    session["memory"] = memory
    save_session(session, settings=settings)
    with pytest.raises(ValueError, match="session memory"):
        load_session(session["session_id"], settings=settings)
