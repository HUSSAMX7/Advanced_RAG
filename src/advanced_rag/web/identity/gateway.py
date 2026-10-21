"""ASGI forwarding adapter; owner operations live in services.py."""

import asyncio

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from . import services


async def dispatch(state, scope, receive, send):
    request = Request(scope)
    workspace = None
    task = asyncio.current_task()
    started = False

    async def tracked_send(message):
        nonlocal started
        if message["type"] == "http.response.start":
            started = True
            message["headers"].append((b"cache-control", b"no-store"))
        await send(message)

    try:
        key, owner = await services.resolve_owner(
            state,
            authorization=request.headers.get("authorization"),
            guest_token=request.headers.get("x-guest-token", ""),
        )
        workspace = await services.open_workspace(state, key)
        if owner["kind"] == "guest":
            services.get_guest(state, request.headers.get("x-guest-token", ""))
        workspace.requests.add(task)
        await workspace.app(scope, receive, tracked_send)
    except HTTPException as exc:
        await JSONResponse(
            {"detail": exc.detail},
            status_code=exc.status_code,
            headers={"Cache-Control": "no-store"},
        )(scope, receive, send)
    except asyncio.CancelledError:
        if not started:
            await JSONResponse({"detail": "انتهت جلسة الضيف."}, status_code=401)(
                scope, receive, send
            )
    finally:
        if workspace is not None:
            workspace.requests.discard(task)


class OwnerGateway:
    """Required ASGI callable contract: Starlette treats plain functions as HTTP handlers.

    This adapter only forwards to a function; it contains no business operations.
    """

    def __init__(self, state):
        self.state = state

    async def __call__(self, scope, receive, send):
        await dispatch(self.state, scope, receive, send)
