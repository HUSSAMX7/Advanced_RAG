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
    lightonocr_model: str = "lightonai/LightOnOCR-2-1B"
    lightonocr_dpi: int = Field(default=200, gt=0)
    lightonocr_concurrency: int = Field(default=64, gt=0)
    lightonocr_max_tokens: int = Field(default=4096, gt=0)
    lightonocr_timeout_seconds: float = Field(default=300, gt=0)
    lightonocr_postprocess: bool = True
    faiss_persist_dir: Path = Path("storage/pdf_documents")
    embedding_model: str = "text-embedding-3-small"
    agent_model: str = "gpt-4o-mini"
    rerank_model: str = "gpt-4o-mini"
    retrieval_candidates: int = Field(default=20, gt=0)
    retrieval_top_k: int = Field(default=5, gt=0)
    chat_sessions_dir: Path = Path("chat_sessions")
    web_data_dir: Path = Path("storage/library")
    max_upload_bytes: int = Field(default=50 * 1024 * 1024, gt=0)
    libreoffice_path: str | None = None


def require_openai_key(settings: Settings) -> str:
    if not settings.openai_api_key or not settings.openai_api_key.get_secret_value():
        raise ValueError("OPENAI_API_KEY is required for this operation")
    return settings.openai_api_key.get_secret_value()
