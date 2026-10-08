import asyncio
import json

import httpx
import pytest
from conftest import api_client, response_payload

from advanced_rag.agent import ask_agent
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.retrieval import load_search_context


def tool_response(query):
    response = response_payload({})
    response["output"] = [
        {
            "id": "fc_search",
            "type": "function_call",
            "name": "search_documents",
            "call_id": "call_search",
            "arguments": json.dumps({"query": query}),
            "status": "completed",
        }
    ]
    return response


@pytest.mark.parametrize("with_documents", [False, True])
def test_general_questions_do_not_require_training_or_search_and_can_resume(corpus, with_documents):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding) if with_documents else None
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        assert body["tool_choice"] == ("auto" if with_documents else "none")
        assert bool(body["tools"]) is with_documents
        if len(requests) == 2:
            assert "التمثيل الضوئي" in json.dumps(body["input"], ensure_ascii=False)
        return httpx.Response(
            200,
            json=response_payload(
                {"answer": "التمثيل الضوئي يحول الضوء إلى طاقة.", "cited_chunk_ids": []}
            ),
        )

    async def run():
        async with api_client(respond) as client:
            first = await ask_agent(
                "اشرح التمثيل الضوئي", context=context, client=client, settings=settings
            )
            return await ask_agent(
                "بسط الشرح",
                context=context,
                client=client,
                settings=settings,
                session_id=first["session_id"],
            )

    answer = asyncio.run(run())
    assert answer["answer"] == "التمثيل الضوئي يحول الضوء إلى طاقة."
    assert answer["sources"] == []
    assert len(requests) == 2
    assert len(load_session(answer["session_id"], settings=settings)["turns"]) == 2


def test_general_answer_cannot_claim_a_document_source(corpus):
    settings, _ = corpus

    async def run():
        async with api_client(
            lambda request: httpx.Response(
                200,
                json=response_payload({"answer": "Invented [1]", "cited_chunk_ids": ["unknown"]}),
            )
        ) as client:
            return await ask_agent("Hello", context=None, client=client, settings=settings)

    with pytest.raises(RuntimeError, match="invalid answer or citations"):
        asyncio.run(run())
    assert not settings.chat_sessions_dir.exists()


def test_general_answers_can_include_brackets_in_code(corpus):
    settings, _ = corpus

    async def run():
        async with api_client(
            lambda request: httpx.Response(
                200,
                json=response_payload(
                    {"answer": "Use `a[0]` to get the first item of `[1]`.", "cited_chunk_ids": []}
                ),
            )
        ) as client:
            return await ask_agent(
                "How do Python lists work?", context=None, client=client, settings=settings
            )

    answer = asyncio.run(run())
    assert answer["answer"] == "Use `a[0]` to get the first item of `[1]`."
    assert answer["sources"] == []


def test_general_answer_never_loads_the_document_index(corpus):
    settings, _ = corpus

    async def load_context():
        raise AssertionError("General conversation must not wait for index loading")

    async def run():
        async with api_client(
            lambda request: httpx.Response(
                200, json=response_payload({"answer": "Hello!", "cited_chunk_ids": []})
            )
        ) as client:
            return await ask_agent("Hello", context=load_context, client=client, settings=settings)

    assert asyncio.run(run())["answer"] == "Hello!"


@pytest.mark.parametrize("lazy", [False, True])
def test_agent_answers_with_a_real_source_and_saves_a_resumable_session(corpus, lazy):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    requests = []
    loads = []

    async def load_context():
        loads.append(True)
        return context

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response("ZX-774"))
        if len(requests) == 2:
            return httpx.Response(
                200, json=response_payload({"ordered_ids": ["identifier", "semantic"]})
            )
        assert body["tool_choice"] == "none"
        output = next(item for item in body["input"] if item.get("type") == "function_call_output")
        assert output["call_id"] == "call_search"
        assert "Invoice ZX-774 costs 120 dollars" in output["output"]
        return httpx.Response(
            200,
            json=response_payload(
                {
                    "answer": "قيمة الفاتورة 120 دولارًا [1]",
                    "cited_chunk_ids": ["identifier"],
                }
            ),
        )

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "كم قيمة ZX-774؟",
                context=load_context if lazy else context,
                client=client,
                settings=settings,
            )

    answer = asyncio.run(run())
    assert answer["answer"] == "قيمة الفاتورة 120 دولارًا [1]"
    assert answer["sources"] == [
        {
            "chunk_id": "identifier",
            "citation": 1,
            "metadata": {"source": "invoice.pdf", "page_num": 3, "section_id": "2: Invoices"},
        }
    ]
    assert (
        load_session(answer["session_id"], settings=settings)["turns"][0]["question"]
        == "كم قيمة ZX-774؟"
    )
    assert len(requests) == 3
    assert len(loads) == (1 if lazy else 0)


def test_resumed_followup_uses_recent_history_and_keeps_all_saved_turns(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    session = load_session(None, settings=settings)
    session["turns"] = [
        {"question": f"Earlier {i}", "answer": "Invoice ZX-774 costs 120 dollars", "sources": []}
        for i in range(12)
    ]
    save_session(session, settings=settings)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            users = [item["content"] for item in body["input"] if item.get("role") == "user"]
            assert users == [*(f"Earlier {i}" for i in range(2, 12)), "Which currency was that?"]
            assert "ZX-774" in json.dumps(body["input"])
            return httpx.Response(200, json=tool_response("ZX-774"))
        if len(requests) == 2:
            return httpx.Response(
                200, json=response_payload({"ordered_ids": ["identifier", "semantic"]})
            )
        return httpx.Response(
            200,
            json=response_payload(
                {
                    "answer": "The invoice uses dollars [1].",
                    "cited_chunk_ids": ["identifier"],
                }
            ),
        )

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "Which currency was that?",
                context=context,
                client=client,
                settings=settings,
                session_id=session["session_id"],
            )

    answer = asyncio.run(run())
    assert answer["session_id"] == session["session_id"]
    resumed = load_session(session["session_id"], settings=settings)
    assert len(resumed["turns"]) == 13
    assert resumed["turns"][0]["question"] == "Earlier 0"
    assert resumed["turns"][-1]["answer"] == "The invoice uses dollars [1]."


@pytest.mark.parametrize(
    "data",
    [
        {"answer": "Fabricated source [1]", "cited_chunk_ids": ["unknown"]},
        {"answer": "Wrong page reference [2]", "cited_chunk_ids": ["identifier"]},
        {"answer": "Uncited answer", "cited_chunk_ids": ["identifier"]},
        {"answer": "", "cited_chunk_ids": []},
    ],
)
def test_invalid_answer_does_not_change_a_saved_session(corpus, data):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    session = load_session(None, settings=settings)
    session["turns"].append(
        {"question": "Previous question", "answer": "Previous answer", "sources": []}
    )
    save_session(session, settings=settings)
    requests = []

    def respond(request):
        requests.append(request)
        payload = (
            tool_response("ZX-774")
            if len(requests) == 1
            else response_payload({"ordered_ids": ["identifier", "semantic"]})
            if len(requests) == 2
            else response_payload(data)
        )
        return httpx.Response(200, json=payload)

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "How much?",
                context=context,
                client=client,
                settings=settings,
                session_id=session["session_id"],
            )

    with pytest.raises(RuntimeError, match="invalid answer or citations"):
        asyncio.run(run())
    assert load_session(session["session_id"], settings=settings) == session


def test_agent_rejects_a_second_search_call(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    payload = tool_response("ZX-774")
    payload["output"].append({**payload["output"][0], "id": "fc_other", "call_id": "other"})

    async def run():
        async with api_client(lambda request: httpx.Response(200, json=payload)) as client:
            return await ask_agent("How much?", context=context, client=client, settings=settings)

    with pytest.raises(RuntimeError, match="exactly one"):
        asyncio.run(run())
    assert not settings.chat_sessions_dir.exists()


def test_insufficient_evidence_is_saved_as_an_answer_without_sources(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    requests = []

    def respond(request):
        requests.append(request)
        payload = (
            tool_response("ZX-774")
            if len(requests) == 1
            else response_payload({"ordered_ids": ["identifier", "semantic"]})
            if len(requests) == 2
            else response_payload(
                {
                    "answer": "I could not find the invoice owner's age in the documents.",
                    "cited_chunk_ids": [],
                }
            )
        )
        return httpx.Response(200, json=payload)

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "How old is the invoice owner?", context=context, client=client, settings=settings
            )

    answer = asyncio.run(run())
    assert answer["sources"] == []
    assert "could not find" in answer["answer"]


def test_openai_failure_is_reported_without_saving_a_turn(corpus):
    from openai import APIStatusError

    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)

    async def run():
        async with api_client(
            lambda request: httpx.Response(503, json={"error": {"message": "Unavailable"}})
        ) as client:
            return await ask_agent("How much?", context=context, client=client, settings=settings)

    with pytest.raises(APIStatusError):
        asyncio.run(run())
    assert not settings.chat_sessions_dir.exists()


def test_uncited_claim_is_not_returned_or_saved_as_a_supported_answer(corpus):
    settings, embedding = corpus
    context = load_search_context(settings, embed_model=embedding)
    requests = []

    def respond(request):
        requests.append(request)
        payload = (
            tool_response("ZX-774")
            if len(requests) == 1
            else response_payload({"ordered_ids": ["identifier", "semantic"]})
            if len(requests) == 2
            else response_payload(
                {"answer": "The invoice costs 999 dollars.", "cited_chunk_ids": []}
            )
        )
        return httpx.Response(200, json=payload)

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "How much is ZX-774?", context=context, client=client, settings=settings
            )

    result = asyncio.run(run())
    expected = "I could not find sufficient information in the documents to answer this question."
    assert result["answer"] == expected
    assert result["sources"] == []
    assert load_session(result["session_id"], settings=settings)["turns"][-1]["answer"] == expected
