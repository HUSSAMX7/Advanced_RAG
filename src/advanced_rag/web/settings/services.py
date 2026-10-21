"""Owner-specific settings operations with explicit state and encryption dependencies."""

from dataclasses import dataclass
from pathlib import Path

from cryptography.fernet import InvalidToken
from pydantic import SecretStr

from ...config import Settings
from ..assistants import services as assistants
from ..files import processing
from ..files.processing import LibraryConflict
from . import credentials, repository
from .schemas import KEY_FIELDS, PUBLIC_FIELDS, SettingsPatch


@dataclass
class SettingsState:
    """Persisted location and current runtime settings for one owner."""

    path: Path
    current: Settings
    encryption_key: SecretStr | None


def load(baseline):
    state = SettingsState(
        baseline.web_data_dir / "settings.json",
        baseline.model_copy(update={"lightonocr_local": True}),
        baseline.web_credential_encryption_key,
    )
    if state.path.exists():
        try:
            document = repository.read(state.path)
            keys = credentials.decrypt(document, state.encryption_key)
            patch = SettingsPatch.model_validate({**document["preferences"], **keys})
            state.current = proposed_settings(state, patch)
        except (ValueError, KeyError, TypeError, InvalidToken) as exc:
            raise ValueError("تعذر قراءة الإعدادات المحفوظة. راجع مفتاح تشفير الخادم.") from exc
    return state


def proposed_settings(state, patch: SettingsPatch) -> Settings:
    values = {name: value for name, value in patch.model_dump(exclude_none=True).items()}
    for name in KEY_FIELDS:
        if name in patch.model_fields_set:
            value = getattr(patch, name)
            raw = value.get_secret_value().strip() if value else ""
            values[name] = SecretStr(raw) if raw else None
    return state.current.model_copy(update=values)


def save(state, patch):
    proposed = proposed_settings(state, patch)
    keys = {
        name: value.get_secret_value() if (value := getattr(proposed, name)) else None
        for name in KEY_FIELDS
    }
    document = {
        **credentials.encrypt(keys, state.encryption_key),
        "preferences": {name: getattr(proposed, name) for name in PUBLIC_FIELDS},
    }
    repository.write(state.path, document)
    state.current = proposed
    return proposed


def public(state):
    return {
        **{name: getattr(state.current, name) for name in PUBLIC_FIELDS},
        "openai_key_configured": bool(state.current.openai_api_key),
        "llamaparse_key_configured": bool(state.current.llama_parse_api_key),
    }


def libraries(workspace):
    return [
        workspace.library,
        *(
            selected
            for assistant_id, selected in workspace.assistants.libraries.items()
            if assistant_id not in workspace.assistants.deleting
        ),
    ]


def embedding_locked(workspace):
    selected = libraries(workspace)
    for library in selected:
        processing.list_files(
            library,
        )
    return any(processing.has_documents(library) for library in selected)


def read_preferences(workspace):
    return {**public(workspace.web_settings), "embedding_locked": embedding_locked(workspace)}


def save_preferences(workspace, patch):
    if (
        any(
            job.task and not job.task.done()
            for library in libraries(workspace)
            for job in library.jobs.values()
        )
        or any(lock.locked() for lock in workspace.session_locks.values())
        or any(workspace.assistants.inflight.values())
        or workspace.assistants.deleting
    ):
        raise LibraryConflict("انتظر اكتمال التدريب أو الإجابة الحالية قبل حفظ الإعدادات.")
    locked = embedding_locked(workspace)
    if (
        patch.embedding_model
        and patch.embedding_model != workspace.web_settings.current.embedding_model
        and locked
    ):
        raise LibraryConflict(
            "أزل فهرسة الملفات المدرّبة قبل تغيير مودل embeddings، ثم درّبها مجددًا."
        )
    current = save(workspace.web_settings, patch)
    processing.update_settings(workspace.library, current)
    assistants.update_settings(workspace.assistants, current)
    return {**public(workspace.web_settings), "embedding_locked": locked}
