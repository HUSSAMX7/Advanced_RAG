"""Shared workspace lifecycle data; feature operations remain plain functions."""

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .assistants.services import AssistantState
from .files.processing import LibraryState
from .settings.services import SettingsState


@dataclass
class WorkspaceState:
    """One owner shares locks/tasks/settings across its feature routers."""

    web_settings: SettingsState
    library: LibraryState
    assistants: AssistantState
    answer: Any
    require_owner_keys: bool = False
    session_locks: dict[str, asyncio.Lock] = field(default_factory=dict)
    title_tasks: dict[tuple[Path, str], asyncio.Task] = field(default_factory=dict)
