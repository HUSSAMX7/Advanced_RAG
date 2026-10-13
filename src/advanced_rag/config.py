"""Validated pipeline settings, loaded from environment variables or .env."""

from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    pdf_provider: Literal["llamaparse", "lightonocr"] = "llamaparse"
    openai_api_key: SecretStr | None = None
    llama_parse_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=AliasChoices("LLAMA_PARSE_API_KEY", "LLAMA_CLOUD_API_KEY"),
    )
    lightonocr_url: str | None = None
    lightonocr_local: bool = False
    lightonocr_local_timeout_seconds: float = Field(default=1800, gt=0)
    lightonocr_model: str = "lightonai/LightOnOCR-2-1B"
    lightonocr_dpi: int = Field(default=200, gt=0)
    lightonocr_concurrency: int = Field(default=64, gt=0)
    lightonocr_max_tokens: int = Field(default=4096, gt=0)
    lightonocr_timeout_seconds: float = Field(default=300, gt=0)
    lightonocr_postprocess: bool = True
    faiss_persist_dir: Path = Path("storage/pdf_documents")
    embedding_model: str = "text-embedding-3-small"
    agent_model: str = "gpt-6-luna"
    assistant_instructions: str = ""
    title_model: str = "gpt-6-luna"
    rerank_model: str = "BAAI/bge-reranker-v2-m3"
    rerank_batch_size: int = Field(default=1, gt=0)
    rerank_max_length: int = Field(default=2048, gt=0, le=8192)
    retrieval_candidates: int = Field(default=20, gt=0)
    retrieval_top_k: int = Field(default=5, gt=0)
    chat_sessions_dir: Path = Path("chat_sessions")
    web_data_dir: Path = Path("storage/library")
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    libreoffice_path: str | None = None
    web_identity_enabled: bool = True
    supabase_url: str | None = None
    supabase_publishable_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SUPABASE_PUBLISHABLE_KEY", "SUPABASE_ANON_KEY"),
    )
    web_credential_encryption_key: SecretStr | None = None
    guest_session_seconds: int = Field(default=900, gt=0)
    guest_renewal_grace_seconds: int = Field(default=60, gt=0)
    guest_close_grace_seconds: int = Field(default=15, gt=0)


def require_openai_key(settings: Settings) -> str:
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value():
        raise ValueError("أضف مفتاح OpenAI من إعداداتك لاستخدام هذه الخدمة.")
    return settings.openai_api_key.get_secret_value()
