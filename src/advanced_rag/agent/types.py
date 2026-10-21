"""Serializable dictionary inputs and outputs for chat."""

from typing import Any, Literal, NotRequired, TypedDict

Source = TypedDict("Source", {"chunk_id": str, "citation": int, "metadata": dict[str, Any]})
Turn = TypedDict("Turn", {"question": str, "answer": str, "sources": list[Source]})
ConversationMemory = TypedDict("ConversationMemory", {"summary": str, "summarized_turns": int})
Session = TypedDict(
    "Session",
    {
        "session_id": str,
        "turns": list[Turn],
        "title": NotRequired[str],
        "title_status": NotRequired[Literal["idle", "pending", "ready", "error"]],
        "title_question": NotRequired[str],
        "memory": NotRequired[ConversationMemory],
    },
)
AgentAnswer = TypedDict("AgentAnswer", {"answer": str, "sources": list[Source], "session_id": str})
