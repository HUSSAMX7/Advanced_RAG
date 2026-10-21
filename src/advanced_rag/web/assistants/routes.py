"""Assistant HTTP input/output; operations live in services.py."""

from fastapi import APIRouter
from fastapi.responses import Response

from ..dependencies import WorkspaceDependency
from . import services
from .schemas import AssistantFields

router = APIRouter(prefix="/api/assistants", tags=["assistants"])


@router.get("")
async def list_assistants(workspace: WorkspaceDependency):
    return services.list_assistants(workspace.assistants)


@router.post("", status_code=201)
async def create_assistant(body: AssistantFields, workspace: WorkspaceDependency):
    return await services.create_assistant(workspace.assistants, body)


@router.get("/{assistant_id}")
async def read_assistant(assistant_id: str, workspace: WorkspaceDependency):
    return services.get_assistant(workspace.assistants, assistant_id)


@router.put("/{assistant_id}")
async def update_assistant(
    assistant_id: str, body: AssistantFields, workspace: WorkspaceDependency
):
    return services.update_assistant(workspace.assistants, assistant_id, body)


@router.delete("/{assistant_id}", status_code=204)
async def delete_assistant(assistant_id: str, workspace: WorkspaceDependency):
    await services.delete_assistant(workspace, assistant_id)
    return Response(status_code=204)
