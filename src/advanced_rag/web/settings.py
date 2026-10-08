"""Persist web preferences and Windows-protected credentials without exposing keys."""

import base64
import ctypes
import json
import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from ..config import Settings

MODEL_FIELDS = ("agent_model", "embedding_model", "rerank_model", "lightonocr_model")
KEY_FIELDS = ("openai_api_key", "llama_parse_api_key")
PUBLIC_FIELDS = ("pdf_provider", *MODEL_FIELDS)


class SettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pdf_provider: Literal["llamaparse", "lightonocr"] | None = None
    agent_model: str | None = Field(default=None, min_length=1, max_length=512)
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


def _protect(data: bytes, *, decrypt=False) -> bytes:
    """Use user-scoped DPAPI; never fall back to plaintext credential storage."""
    if os.name != "nt":
        raise ValueError("حفظ المفاتيح المحمي متاح على ويندوز في هذه النسخة.")

    class Blob(ctypes.Structure):
        _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.c_void_p)]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    output = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    name = "CryptUnprotectData" if decrypt else "CryptProtectData"
    operation = getattr(crypt, name)
    operation.argtypes = [
        ctypes.POINTER(Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(Blob),
    ]
    operation.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not operation(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise ValueError("تعذر حفظ أو قراءة المفاتيح بحساب ويندوز الحالي.")
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


class WebSettings:
    def __init__(self, baseline: Settings):
        self.path = baseline.web_data_dir / "settings.json"
        self.current = baseline.model_copy(update={"lightonocr_local": True})
        if self.path.exists():
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
                keys = json.loads(_protect(base64.b64decode(document["secrets"]), decrypt=True))
                patch = SettingsPatch.model_validate({**document["preferences"], **keys})
                self.current = self._updated(patch)
            except (ValueError, KeyError, TypeError) as exc:
                raise ValueError("تعذر قراءة الإعدادات المحفوظة بحساب ويندوز الحالي.") from exc

    def _updated(self, patch: SettingsPatch) -> Settings:
        values = {name: value for name, value in patch.model_dump(exclude_none=True).items()}
        for name in KEY_FIELDS:
            if name in patch.model_fields_set:
                value = getattr(patch, name)
                raw = value.get_secret_value().strip() if value else ""
                values[name] = SecretStr(raw) if raw else None
        return self.current.model_copy(update=values)

    def save(self, patch: SettingsPatch) -> Settings:
        proposed = self._updated(patch)
        keys = {
            name: value.get_secret_value() if (value := getattr(proposed, name)) else None
            for name in KEY_FIELDS
        }
        encrypted = _protect(json.dumps(keys).encode())
        document = {
            "preferences": {name: getattr(proposed, name) for name in PUBLIC_FIELDS},
            "secrets": base64.b64encode(encrypted).decode("ascii"),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix="settings-", suffix=".tmp", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump(document, output, ensure_ascii=False)
                output.flush()
                os.fsync(output.fileno())
            temp_path.replace(self.path)
        finally:
            temp_path.unlink(missing_ok=True)
        self.current = proposed
        return proposed

    def public(self):
        return {
            **{name: getattr(self.current, name) for name in PUBLIC_FIELDS},
            "openai_key_configured": bool(self.current.openai_api_key),
            "llamaparse_key_configured": bool(self.current.llama_parse_api_key),
        }
