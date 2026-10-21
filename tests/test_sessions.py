from advanced_rag.agent.sessions import load_session, save_session


def test_a_saved_session_can_be_resumed_with_its_answer_and_sources(corpus):
    settings, _ = corpus
    session = load_session(None, settings=settings)
    session["turns"].append(
        {
            "question": "كم قيمة الفاتورة؟",
            "answer": "120 دولارًا [1]",
            "sources": [
                {
                    "chunk_id": "identifier",
                    "citation": 1,
                    "metadata": {"source": "invoice.pdf", "page_num": 3},
                }
            ],
        }
    )
    save_session(session, settings=settings)
    resumed = load_session(session["session_id"], settings=settings)
    assert resumed["turns"] == [
        {
            "question": "كم قيمة الفاتورة؟",
            "answer": "120 دولارًا [1]",
            "sources": [
                {
                    "chunk_id": "identifier",
                    "citation": 1,
                    "metadata": {"source": "invoice.pdf", "page_num": 3},
                }
            ],
        }
    ]


def test_an_explicit_missing_session_is_not_created(corpus):
    settings, _ = corpus
    with pytest.raises(FileNotFoundError, match="session not found"):
        load_session(str(uuid4()), settings=settings)


def test_malformed_saved_session_is_rejected(corpus):
    settings, _ = corpus
    session = load_session(None, settings=settings)
    save_session(session, settings=settings)
    path = settings.chat_sessions_dir / f"{session['session_id']}.json"
    path.write_text(json.dumps({"session_id": session["session_id"], "turns": [None]}))
    with pytest.raises(ValueError, match="Invalid chat session"):
        load_session(session["session_id"], settings=settings)


def test_session_id_cannot_select_an_arbitrary_file(corpus):
    settings, _ = corpus
    with pytest.raises(ValueError, match="UUID"):
        load_session("../other-file", settings=settings)


import json
from uuid import uuid4

import pytest
