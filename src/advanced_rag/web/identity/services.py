"""Verified ownership and renewable guest workspace operations."""

import asyncio
import base64
import hashlib
import json
import logging
import secrets
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException

from . import repository

logger = logging.getLogger(__name__)


@dataclass
class OwnedWorkspace:
    """ASGI application, teardown stack and its tracked active requests."""

    app: Any
    stack: AsyncExitStack
    requests: set = field(default_factory=set)


@dataclass
class OwnerState:
    """Shared lifecycle data; operations are explicit-state functions."""

    settings: Any
    factory: Any
    prepare: Any
    embed_model: Any
    answer: Any
    clock: Any
    root: Path
    database: Path
    auth: Any = None
    http_client: Any = None
    workspaces: dict[str, OwnedWorkspace] = field(default_factory=dict)
    open_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    operation_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    cleanups: dict[str, asyncio.Task] = field(default_factory=dict)


def validate_public_key(public_key):
    if public_key and not public_key.startswith("sb_publishable_"):
        try:
            payload = public_key.split(".")[1]
            claims = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            if claims.get("role") != "anon":
                raise ValueError()
        except (ValueError, IndexError, TypeError, AttributeError):
            raise ValueError(
                "استخدم مفتاح Supabase publishable/anon؛ لا تستخدم مفتاحًا سريًا."
            ) from None


def initialize(settings, factory, *, prepare, embed_model, answer, clock):
    validate_public_key(settings.supabase_publishable_key)
    root = settings.web_data_dir / "owners"
    root.mkdir(parents=True, exist_ok=True)
    database = settings.web_data_dir / "identity.sqlite3"
    repository.initialize(database)
    return OwnerState(settings, factory, prepare, embed_model, answer, clock, root, database)


@asynccontextmanager
async def running(state):
    sweep(state)
    task = asyncio.create_task(sweeper(state))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await asyncio.gather(*state.cleanups.values(), return_exceptions=True)
        await asyncio.gather(*(w.stack.aclose() for w in state.workspaces.values()))
        state.workspaces.clear()


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def create_guest(state):
    token = secrets.token_urlsafe(32)
    guest_id = str(uuid4())
    renew_at = state.clock() + state.settings.guest_session_seconds
    expires_at = renew_at + state.settings.guest_renewal_grace_seconds
    repository.insert(state.database, guest_id, digest(token), renew_at, expires_at)
    return {"token": token, **guest_public(state, get_guest(state, token))}


def get_guest(state, token):
    if not token or len(token) > 200:
        raise HTTPException(401, "ابدأ جلسة ضيف جديدة أو سجّل الدخول.")
    row = repository.get(state.database, digest(token))
    now = state.clock()
    if (
        row is None
        or row["revoked"]
        or row["expires_at"] <= now
        or (row["close_at"] is not None and row["close_at"] <= now)
    ):
        sweep(state)
        raise HTTPException(401, "انتهت جلسة الضيف. ابدأ جلسة جديدة أو سجّل الدخول.")
    return dict(row)


def guest_public(state, row):
    return {
        "kind": "guest",
        "id": row["id"],
        "renew_at": row["renew_at"],
        "expires_at": row["expires_at"],
        "server_time": state.clock(),
    }


def renew(state, token):
    row = get_guest(state, token)
    now = state.clock()
    if now < row["renew_at"]:
        raise HTTPException(409, "لم يحن موعد تجديد الجلسة بعد.")
    renew_at = now + state.settings.guest_session_seconds
    repository.renew(
        state.database, row["id"], renew_at, renew_at + state.settings.guest_renewal_grace_seconds
    )
    return guest_public(state, get_guest(state, token))


def navigation(state, token, *, resume):
    row = get_guest(state, token)
    deadline = None if resume else state.clock() + state.settings.guest_close_grace_seconds
    repository.set_close_deadline(state.database, row["id"], deadline)
    return guest_public(state, get_guest(state, token))


def end(state, token):
    guest_id = repository.revoke_token(state.database, digest(token))
    if guest_id:
        schedule_cleanup(state, guest_id)


def sweep(state):
    for guest_id in repository.revoke_expired(state.database, state.clock()):
        schedule_cleanup(state, guest_id)


def schedule_cleanup(state, guest_id):
    if guest_id not in state.cleanups:
        state.cleanups[guest_id] = asyncio.create_task(purge(state, guest_id))


async def sweeper(state):
    while True:
        sweep(state)
        await asyncio.sleep(1)


async def purge(state, guest_id):
    try:
        async with state.open_lock:
            workspace = state.workspaces.pop("guests/" + guest_id, None)
            if workspace:
                tasks = list(workspace.requests)
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                # Lifespan cancels title work and awaits training before removal.
                await workspace.stack.aclose()
            await asyncio.to_thread(repository.remove, state.database, state.root, guest_id)
    except Exception:
        # Revocation remains persisted; the sweeper retries failed cleanup.
        logger.exception("Guest cleanup failed for %s", guest_id)
    finally:
        state.cleanups.pop(guest_id, None)


async def open_workspace(state, key):
    async with state.open_lock:
        if key not in state.workspaces:
            directory = state.root / key
            baseline = state.settings.model_copy(
                update={
                    "web_identity_enabled": False,
                    "web_data_dir": directory,
                    "faiss_persist_dir": directory / "index",
                    "chat_sessions_dir": directory / "conversations",
                    # BYOK owners must not inherit server/legacy credentials.
                    "openai_api_key": None,
                    "llama_parse_api_key": None,
                    "assistant_instructions": "",
                }
            )
            app = state.factory(
                baseline,
                prepare=state.prepare,
                embed_model=state.embed_model,
                answer=state.answer,
                mutation_lock=state.operation_lock,
                require_owner_keys=True,
            )
            stack = AsyncExitStack()
            try:
                await stack.enter_async_context(app.router.lifespan_context(app))
            except BaseException:
                await stack.aclose()
                raise
            state.workspaces[key] = OwnedWorkspace(app, stack)
        return state.workspaces[key]


async def resolve_owner(state, *, authorization, guest_token):
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise HTTPException(401, "تسجيل الدخول غير صالح.")
        user = await state.auth(token)
        try:
            user_id = str(UUID(user["id"]))
            if not user.get("email_confirmed_at") or not user.get("email"):
                raise ValueError()
            if user.get("is_anonymous"):
                raise ValueError()
        except (KeyError, ValueError, TypeError, AttributeError):
            raise HTTPException(401, "تحقق من إيميلك لإكمال الدخول.") from None
        return "accounts/" + user_id, {"kind": "account", "id": user_id, "email": user["email"]}
    token = guest_token
    row = get_guest(state, token)
    return "guests/" + row["id"], guest_public(state, row)
