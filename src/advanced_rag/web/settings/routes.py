"""Owner settings HTTP routes."""

from fastapi import APIRouter

from ..dependencies import WorkspaceDependency
from . import services
from .schemas import SettingsPatch

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def read_settings(workspace: WorkspaceDependency):
    return services.read_preferences(workspace)


@router.put("")
async def save_settings(body: SettingsPatch, workspace: WorkspaceDependency):
    return services.save_preferences(workspace, body)
