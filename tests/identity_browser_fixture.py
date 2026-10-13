"""Local-only, disposable identity UI QA with a simulated email service.

uv run python tests/identity_browser_fixture.py
No real mail, credentials, document APIs or Supabase account are used.
POST /qa/advance?seconds=900 advances ONLY this fixture's guest clock.
GET /qa/verify simulates clicking the email verification link.
"""

import base64
import json
import tempfile
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from pydantic import SecretStr

from advanced_rag import Settings
from advanced_rag.agent.sessions import load_session, save_session
from advanced_rag.config import require_openai_key
from advanced_rag.web.app import create_app


class Clock:
    offset = 0

    def __call__(self):
        return time.time() + self.offset


def encoded(value):
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="rag-identity-qa-") as temporary:
        clock = Clock()
        user = {
            "id": "41806e31-3c27-4444-bf25-4eb91c4ab21a",
            "email": "qa@example.com",
            "email_confirmed_at": "2026-10-13T00:00:00Z",
            "aud": "authenticated",
            "role": "authenticated",
            "identities": [],
            "app_metadata": {},
            "user_metadata": {},
            "created_at": "2026-10-13T00:00:00Z",
        }
        token = ".".join(
            [
                encoded({"alg": "HS256", "typ": "JWT"}),
                encoded(
                    {"sub": user["id"], "exp": int(time.time()) + 3600, "aud": "authenticated"}
                ),
                "local-fixture-signature",
            ]
        )

        async def verify(value):
            if value != token:
                raise HTTPException(401, "Invalid fixture token")
            return user

        async def prepare(resource, settings, progress):
            require_openai_key(settings)
            if resource["file_name"].endswith(".pdf") and not settings.llama_parse_api_key:
                raise ValueError("أضف مفتاح LlamaParse من إعداداتك.")
            return [
                TextNode(
                    text="محتوى تجريبي محلي",
                    metadata={"resource_id": resource["resource_id"]},
                )
            ]

        async def answer(question, *, settings, session_id, **kwargs):
            require_openai_key(settings)
            text = "هذه إجابة تجريبية محلية لا تستدعي أي خدمة خارجية."
            session = load_session(session_id, settings=settings)
            session["turns"].append({"question": question, "answer": text, "sources": []})
            save_session(session, settings=settings)
            return {"session_id": session_id, "answer": text, "sources": []}

        application = create_app(
            Settings(
                _env_file=None,
                web_data_dir=Path(temporary) / "library",
                web_credential_encryption_key=SecretStr(Fernet.generate_key().decode()),
                supabase_url="http://127.0.0.1:8004/supabase",
                supabase_publishable_key="sb_publishable_local_fixture",
            ),
            identity_verifier=verify,
            clock=clock,
            prepare=prepare,
            embed_model=MockEmbedding(embed_dim=2),
            answer=answer,
        )

        @asynccontextmanager
        async def lifespan(app):
            async with application.router.lifespan_context(application):
                yield

        fixture = FastAPI(lifespan=lifespan)

        @fixture.post("/qa/advance")
        async def advance(seconds: int):
            clock.offset += seconds
            return {"advanced": seconds}

        @fixture.get("/qa/verify")
        async def verification_link():
            return RedirectResponse("/?code=fixture-verification")

        @fixture.post("/supabase/auth/v1/otp")
        async def email(request: Request):
            body = await request.json()
            user["email"] = body["email"]
            return {}

        @fixture.post("/supabase/auth/v1/token")
        async def exchange():
            return {
                "access_token": token,
                "refresh_token": "fixture-refresh-token",
                "token_type": "bearer",
                "expires_in": 3600,
                "user": user,
            }

        @fixture.get("/supabase/auth/v1/user")
        async def current():
            return user

        @fixture.post("/supabase/auth/v1/logout", status_code=204)
        async def logout():
            return None

        fixture.mount("/", application)
        uvicorn.run(fixture, host="127.0.0.1", port=8004)
