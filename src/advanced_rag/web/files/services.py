"""File transfer and indexing operations; HTTP formatting stays in routes."""

import asyncio
from pathlib import Path
from uuid import uuid4

from ...config import require_openai_key
from ...ingestion.documents import prepare_document
from . import processing, repository
from .schemas import public

SUPPORTED = {".pdf", ".doc", ".docx", ".txt"}


class UploadTooLarge(Exception):
    """HTTP adapts this specific file-limit failure to status 413."""


async def upload(file, library):
    name = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED or not name or len(name) > 255:
        raise ValueError("الصيغ المدعومة: PDF وDOCX وDOC وTXT.")
    file_id = str(uuid4())
    original = file_id + suffix
    path = repository.uploads(library.registry) / original
    size = 0
    try:
        with path.open("wb") as output:
            while block := await file.read(1024 * 1024):
                size += len(block)
                if size > library.settings.max_upload_bytes:
                    raise UploadTooLarge()
                await asyncio.to_thread(output.write, block)
        if size == 0:
            raise ValueError("لا يمكن رفع ملف فارغ.")
        if suffix == ".pdf":
            with path.open("rb") as source:
                if b"%PDF-" not in source.read(1024):
                    raise ValueError("الملف المرفوع ليس PDF صالحًا.")
        row = repository.add(
            library.registry,
            name,
            size,
            file_id=file_id,
            original=original,
            image_support=suffix == ".pdf",
        )
        return public(row)
    finally:
        await file.close()
        try:
            repository.get(library.registry, file_id)
        except FileNotFoundError:
            path.unlink(missing_ok=True)


def train(library, file_id, *, require_owner_keys):
    row = repository.get(library.registry, file_id)
    if require_owner_keys and library.prepare is prepare_document:
        require_openai_key(library.settings)
        if (
            row["type"] == "pdf"
            and library.settings.pdf_provider == "llamaparse"
            and not library.settings.llama_parse_api_key
        ):
            raise ValueError("أضف مفتاح LlamaParse من إعداداتك لاستخراج ملف PDF.")
    return processing.train(library, file_id)


def original_file(library, file_id):
    row = repository.get(library.registry, file_id)
    if not row["original"]:
        raise FileNotFoundError("الملف الأصلي غير متوفر؛ أُضيف من سطر الأوامر.")
    return repository.uploads(library.registry) / row["original"], row["name"]


def source(library, chunk_id, assistant_id):
    result = processing.source(library, chunk_id)
    if assistant_id:
        for image in result.get("images", []):
            image["url"] = f"/api/assistants/{assistant_id}/sources/{chunk_id}/images/{image['id']}"
    return result
