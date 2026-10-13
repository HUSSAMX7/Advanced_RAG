"""Optional sign-in and guest session HTTP routes."""

from fastapi import APIRouter, Request

from . import services
from .dependencies import OwnerDependency, principal
from .schemas import GuestToken

router = APIRouter(prefix="/api/auth", tags=["identity"])


@router.get("/config")
async def config(state: OwnerDependency):
    configured = bool(state.settings.supabase_url and state.settings.supabase_publishable_key)
    return {
        "enabled": True,
        "configured": configured,
        "supabase_url": state.settings.supabase_url if configured else None,
        "publishable_key": state.settings.supabase_publishable_key if configured else None,
    }


@router.post("/guest", status_code=201)
async def create_guest(state: OwnerDependency):
    return services.create_guest(state)


@router.get("/session")
async def current(request: Request):
    _, owner = await principal(request)
    return owner


@router.post("/guest/renew")
async def renew(request: Request, state: OwnerDependency):
    return services.renew(state, request.headers.get("x-guest-token", ""))


@router.post("/guest/resume")
async def resume(request: Request, state: OwnerDependency):
    return services.navigation(state, request.headers.get("x-guest-token", ""), resume=True)


@router.post("/guest/closing", status_code=202)
async def closing(body: GuestToken, state: OwnerDependency):
    services.navigation(state, body.token.get_secret_value(), resume=False)
    return {"closing": True}


@router.post("/guest/end", status_code=202)
async def end(body: GuestToken, state: OwnerDependency):
    services.end(state, body.token.get_secret_value())
    return {"ended": True}


local_router = APIRouter(prefix="/api/auth", tags=["identity"])


@local_router.get("/config")
async def local_config():
    return {"enabled": False}
