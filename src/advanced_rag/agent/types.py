"""Serializable dictionary inputs and outputs for chat."""

from typing import Any, TypedDict

Source = TypedDict("Source", {"chunk_id": str, "citation": int, "metadata": dict[str, Any]})
Turn = TypedDict("Turn", {"question": str, "answer": str, "sources": list[Source]})
Session = TypedDict("Session", {"session_id": str, "turns": list[Turn]})
AgentAnswer = TypedDict("AgentAnswer", {"answer": str, "sources": list[Source], "session_id": str})
