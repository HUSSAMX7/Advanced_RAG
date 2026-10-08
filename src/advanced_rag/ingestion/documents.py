"""Prepare PDF, Word and plain-text uploads for the shared FAISS store."""

import asyncio
import io
import shutil
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

from ..config import Settings
from ..models import PdfResource
from ..visuals import enrich_pdf_chunks
from .chunking import create_chunks
from .providers import get_pdf_extractor


def libreoffice_executable(settings: Settings) -> str | None:
    candidates = [
        settings.libreoffice_path,
        shutil.which("soffice"),
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
    ]
    return next((str(path) for path in candidates if path and Path(path).is_file()), None)


def _word_text(data: bytes) -> str:
    document = Document(io.BytesIO(data))
    parts = []
    for block in document.iter_inner_content():
        if isinstance(block, Paragraph):
            parts.append(block.text)
        elif isinstance(block, Table):
            parts.extend(" | ".join(cell.text for cell in row.cells) for row in block.rows)
    return "\n\n".join(parts)


async def _convert_doc(data: bytes, settings: Settings) -> bytes:
    executable = libreoffice_executable(settings)
    if executable is None:
        raise ValueError("صيغة DOC تحتاج LibreOffice. ثبّته أو ارفع الملف بصيغة DOCX.")
    with tempfile.TemporaryDirectory(prefix="rag-word-") as directory:
        base = Path(directory)
        (base / "input.doc").write_bytes(data)
        process = await asyncio.create_subprocess_exec(
            executable,
            "--headless",
            "--norestore",
            f"-env:UserInstallation={(base / 'profile').as_uri()}",
            "--convert-to",
            "docx",
            "--outdir",
            directory,
            str(base / "input.doc"),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            **({"creationflags": 0x08000000} if sys.platform == "win32" else {}),
        )
        try:
            await asyncio.wait_for(process.wait(), timeout=120)
            output = base / "input.docx"
            if process.returncode != 0 or not output.exists():
                raise ValueError("تعذر تحويل ملف DOC. تأكد من سلامة الملف وأنه غير محمي.")
            return output.read_bytes()
        except TimeoutError as exc:
            raise ValueError("انتهت مهلة تحويل ملف DOC. حاول استخدام DOCX.") from exc
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()


async def prepare_document(
    resource: PdfResource,
    settings: Settings,
    progress: Callable[[str], None],
) -> list[TextNode]:
    """Return chunks only; publication and cancellation are managed by the library."""
    suffix = Path(resource["file_name"]).suffix.lower()
    progress("extracting")
    if suffix == ".pdf":
        nodes = await get_pdf_extractor(settings, progress=progress)(resource)
        nodes = [node for node in nodes if node.get_content().strip()]
    else:
        data = resource["data"]
        if suffix == ".doc":
            data = await _convert_doc(data, settings)
        if suffix in {".doc", ".docx"}:
            text = await asyncio.to_thread(_word_text, data)
        elif suffix == ".txt":
            try:
                text = data.decode("utf-8-sig")
            except UnicodeError as exc:
                raise ValueError("احفظ ملف TXT بترميز UTF-8 ثم أعد رفعه.") from exc
        else:
            raise ValueError("الصيغ المدعومة: PDF وDOCX وDOC وTXT.")
        nodes = [TextNode(text=text)] if text.strip() else []
    include_images = suffix == ".pdf" and resource.get("include_images", False)
    if not nodes and not include_images:
        raise ValueError("الملف لا يحتوي نصًا يمكن تدريبه.")
    for node in nodes:
        node.metadata.update(
            {
                "resource_id": resource["resource_id"],
                "source": resource["file_name"],
                "paper_path": resource["file_name"],
                "file_type": suffix.lstrip("."),
                "assistant_id": settings.faiss_persist_dir.name,
            }
        )
    progress("chunking")
    if suffix == ".pdf" and nodes:
        chunks = await create_chunks({resource["file_name"]: nodes}, settings=settings)
    elif suffix == ".pdf":
        chunks = []
    else:
        for node in nodes:
            node.metadata["section_id"] = f"0: {resource['file_name']}"
            node.metadata["sub_section_id"] = node.metadata["section_id"]
        chunks = SentenceSplitter(chunk_size=1024, chunk_overlap=50)(nodes)
    chunks = [node for node in chunks if node.get_content().strip()]
    if include_images:
        progress("describing_images")
        chunks = await enrich_pdf_chunks(resource, nodes, chunks, settings)
    if not chunks:
        raise ValueError("لم ينتج عن الملف أي مقاطع قابلة للحفظ.")
    if any(not isinstance(node, TextNode) for node in chunks):
        raise ValueError("Document splitting returned a non-text chunk")
    chunks = [node for node in chunks if isinstance(node, TextNode)]
    return chunks
