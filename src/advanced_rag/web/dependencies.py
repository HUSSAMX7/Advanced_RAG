"""Request dependency resolution shared by the feature routers."""

from typing import Annotated

from fastapi import Depends, Request

from .assistants.services import get_library
from .files.processing import LibraryState
from .state import WorkspaceState


def get_workspace(request: Request) -> WorkspaceState:
    return request.app.state.workspace


async def active_library(request: Request):
    workspace = get_workspace(request)
    assistant_id = request.path_params.get("assistant_id")
    if assistant_id is None:
        yield workspace.library
        return
    state = workspace.assistants
    selected = get_library(state, assistant_id)
    state.inflight[assistant_id] = state.inflight.get(assistant_id, 0) + 1
    try:
        yield selected
    finally:
        state.inflight[assistant_id] -= 1


LibraryDependency = Annotated[LibraryState, Depends(active_library)]
WorkspaceDependency = Annotated[WorkspaceState, Depends(get_workspace)]
