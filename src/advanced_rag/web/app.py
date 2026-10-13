"""Create FastAPI applications, register feature routers and wire their lifecycles."""

import asyncio
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from filelock import FileLock
from starlette.routing import Route

from ..agent import ask_agent
from ..config import Settings
from ..ingestion.documents import prepare_document
from . import errors
from .assistants import routes as assistant_routes
from .assistants import services as assistants
from .conversations import routes as conversation_routes
from .conversations import services as conversations
from .files import processing
from .files import routes as file_routes
from .identity import routes as identity_routes
from .identity import services as identity
from .identity.gateway import OwnerGateway
from .identity.providers import verify_supabase_token
from .settings import routes as settings_routes
from .settings import services as preferences
from .state import WorkspaceState
from .system import router as system_router


def mount_frontend(app):
    directory = Path(__file__).resolve().parents[3] / "frontend" / "dist"
    if directory.is_dir():
        app.mount("/", StaticFiles(directory=directory, html=True), name="frontend")
    else:
        app.add_api_route("/", missing_frontend, include_in_schema=False)


async def missing_frontend():
    return {"message": "Build the React client: cd frontend && npm install && npm run build"}


def create_app(
    settings=None,
    *,
    prepare=prepare_document,
    embed_model=None,
    answer=ask_agent,
    identity_verifier=None,
    clock=None,
):
    settings = settings or Settings()
    if settings.web_identity_enabled:
        return create_identity_app(
            settings,
            prepare=prepare,
            embed_model=embed_model,
            answer=answer,
            verifier=identity_verifier,
            clock=clock,
        )
    return _create_workspace_app(settings, prepare=prepare, embed_model=embed_model, answer=answer)


def _create_workspace_app(
    settings, *, prepare, embed_model, answer, mutation_lock=None, require_owner_keys=False
):
    web_settings = preferences.load(settings)
    library = processing.create_library(
        web_settings.current, prepare=prepare, embed_model=embed_model
    )
    if mutation_lock is not None:
        library.mutation_lock = mutation_lock
    assistant_state = assistants.initialize(
        web_settings.current,
        prepare=prepare,
        embed_model=embed_model,
        mutation_lock=library.mutation_lock,
    )
    workspace = WorkspaceState(web_settings, library, assistant_state, answer, require_owner_keys)

    @asynccontextmanager
    async def lifespan(app):
        lock = FileLock(str(settings.web_data_dir / ".app.lock"))
        lock.acquire(timeout=0)
        try:
            await processing.start(library)
            await assistants.start(assistant_state)
            await conversations.resume_titles(workspace)
            yield
        finally:
            await conversations.close(workspace)
            await asyncio.gather(processing.close(library), assistants.close(assistant_state))
            lock.release()

    app = FastAPI(title="Advanced RAG Library", lifespan=lifespan)
    app.state.workspace = workspace
    app.state.assistants = assistant_state
    errors.register(app)
    app.include_router(identity_routes.local_router)
    app.include_router(assistant_routes.router)
    app.include_router(settings_routes.router)
    app.include_router(system_router)
    for prefix in ("/api", "/api/assistants/{assistant_id}"):
        app.include_router(file_routes.create_router(prefix))
        app.include_router(conversation_routes.create_router(prefix))
    mount_frontend(app)
    return app


def create_identity_app(settings, *, prepare, embed_model, answer, verifier=None, clock=None):
    owners = identity.initialize(
        settings,
        _create_workspace_app,
        prepare=prepare,
        embed_model=embed_model,
        answer=answer,
        clock=clock or time.time,
    )
    if verifier is None:
        owners.http_client = httpx.AsyncClient(timeout=15, follow_redirects=False)

        async def verify(token):
            return await verify_supabase_token(settings, owners.http_client, token)

        owners.auth = verify
    else:
        owners.auth = verifier

    @asynccontextmanager
    async def lifespan(app):
        lock = FileLock(str(settings.web_data_dir / ".identity.lock"))
        lock.acquire(timeout=0)
        try:
            async with identity.running(owners):
                yield
        finally:
            if owners.http_client is not None:
                await owners.http_client.aclose()
            lock.release()

    app = FastAPI(title="Advanced RAG", lifespan=lifespan)
    app.state.owners = owners
    errors.register(app)
    app.include_router(identity_routes.router)
    app.router.routes.append(
        Route(
            "/api/{path:path}",
            endpoint=OwnerGateway(owners),
            methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"],
        )
    )
    mount_frontend(app)
    return app


def main():
    import uvicorn

    uvicorn.run(create_app(), host="127.0.0.1", port=8001)


if __name__ == "__main__":
    main()
