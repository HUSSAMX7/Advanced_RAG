"""Conversation persistence adapter to the existing agent session store."""

from ...agent.sessions import load_session, save_session


def load(settings, session_id):
    return load_session(session_id, settings=settings)


def save(settings, session, *, preserve_title=True):
    return save_session(session, settings=settings, preserve_title=preserve_title)


def paths(settings):
    return settings.chat_sessions_dir.glob("*.json")
