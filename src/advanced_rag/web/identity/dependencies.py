"""HTTP request adaptation for verified owner identity."""

from typing import Annotated

from fastapi import Depends, Request

from .services import OwnerState, resolve_owner


def get_owner_state(request: Request) -> OwnerState:
    return request.app.state.owners


async def principal(request: Request):
    return await resolve_owner(
        get_owner_state(request),
        authorization=request.headers.get("authorization"),
        guest_token=request.headers.get("x-guest-token", ""),
    )


OwnerDependency = Annotated[OwnerState, Depends(get_owner_state)]
