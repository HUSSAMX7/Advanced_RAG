"""Validated provider preferences and secret input models."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

MODEL_FIELDS = ("agent_model", "title_model", "embedding_model", "rerank_model", "lightonocr_model")
KEY_FIELDS = ("openai_api_key", "llama_parse_api_key")
PUBLIC_FIELDS = ("pdf_provider", *MODEL_FIELDS)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_provider: Literal["llamaparse", "lightonocr"] | None = None
    agent_model: str | None = Field(default=None, min_length=1, max_length=512)
    title_model: str | None = Field(default=None, min_length=1, max_length=512)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=512)
    rerank_model: str | None = Field(default=None, min_length=1, max_length=512)
    lightonocr_model: str | None = Field(default=None, min_length=1, max_length=512)
    openai_api_key: SecretStr | None = Field(default=None, max_length=4096)
    llama_parse_api_key: SecretStr | None = Field(default=None, max_length=4096)

    @field_validator(*MODEL_FIELDS)
    @classmethod
    def nonblank_model(cls, value):
        if value is not None and not value.strip():
            raise ValueError("اكتب اسم المودل.")
        return value.strip() if value is not None else None
