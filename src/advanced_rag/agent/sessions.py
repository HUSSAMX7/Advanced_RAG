"""Save successful chat turns locally without serializing SDK or index objects."""

import json
from uuid import UUID, uuid4

from ..config import Settings
from .titles import fallback_title
from .types import Session


def _session_id(value: str) -> str:
    try:
        canonical = str(UUID(value))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("Session ID must be a UUID") from exc
    if canonical != value:
        raise ValueError("Session ID must be a canonical UUID")
    return canonical


def load_session(session_id: str | None, *, settings: Settings) -> Session:
    """Create an unsaved session or load an explicitly requested existing session."""
    if session_id is None:
        return {
            "session_id": str(uuid4()),
            "turns": [],
            "title": "محادثة جديدة",
            "title_status": "idle",
        }
    path = settings.chat_sessions_dir / f"{_session_id(session_id)}.json"
    try:
        session = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"Chat session not found: {session_id}") from exc
    except (UnicodeError, ValueError) as exc:
        raise ValueError(f"Invalid chat session: {session_id}") from exc
    if (
        not isinstance(session, dict)
        or session.get("session_id") != session_id
        or not isinstance(session.get("turns"), list)
    ):
        raise ValueError(f"Invalid chat session: {session_id}")
    for turn in session["turns"]:
        if (
            not isinstance(turn, dict)
            or not isinstance(turn.get("question"), str)
            or not isinstance(turn.get("answer"), str)
            or not isinstance(turn.get("sources"), list)
        ):
            # The invalid value is persisted JSON, not a caller's Python argument type.
            raise ValueError(f"Invalid chat session: {session_id}")  # noqa: TRY004
        for source in turn["sources"]:
            if (
                not isinstance(source, dict)
                or not isinstance(source.get("chunk_id"), str)
                or type(source.get("citation")) is not int
                or source["citation"] < 1
                or not isinstance(source.get("metadata"), dict)
            ):
                raise ValueError(f"Invalid chat session: {session_id}")
    title = session.get("title")
    if title is not None and (not isinstance(title, str) or not title.strip()):
        raise ValueError(f"Invalid chat session: {session_id}")
    if title is None:
        session["title"] = (
            fallback_title(session["turns"][0]["question"]) if session["turns"] else "محادثة جديدة"
        )
    session.setdefault("title_status", "ready" if session["turns"] else "idle")
    if session["title_status"] not in ("idle", "pending", "ready", "error"):
        raise ValueError(f"Invalid chat session title status: {session_id}")
    if session["title_status"] in ("pending", "error") and (
        not isinstance(session.get("title_question"), str) or not session["title_question"].strip()
    ):
        raise ValueError(f"Invalid chat session title question: {session_id}")
    if "memory" in session:
        memory = session["memory"]
        if (
            not isinstance(memory, dict)
            or not isinstance(memory.get("summary"), str)
            or not memory["summary"].strip()
            or type(memory.get("summarized_turns")) is not int
            or not 0 < memory["summarized_turns"] <= len(session["turns"])
        ):
            raise ValueError(f"Invalid chat session memory: {session_id}")
    return session


def save_session(session: Session, *, settings: Settings, preserve_title: bool = True) -> None:
    """Replace a session atomically so an interrupted write cannot truncate it."""
    session_id = _session_id(session["session_id"])
    settings.chat_sessions_dir.mkdir(parents=True, exist_ok=True)
    path = settings.chat_sessions_dir / f"{session_id}.json"
    if preserve_title and path.exists():
        # The independent title job may have completed since the answer loaded its history.
        latest = load_session(session_id, settings=settings)
        if latest["title_status"] != "idle":
            for key in ("title", "title_status", "title_question"):
                if key in latest:
                    session[key] = latest[key]
                else:
                    session.pop(key, None)
    temporary = path.with_suffix(f".{uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(session, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
