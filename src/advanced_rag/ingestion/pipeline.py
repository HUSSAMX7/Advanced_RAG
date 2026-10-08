"""Connect the supplied PDF extraction, section, and splitting functions to this project."""

import asyncio
import logging
from collections.abc import Callable
from functools import partial

from llama_index.core.schema import TextNode

from ..config import Settings
from ..models import FileStatus, PdfResource, file_status
from .chunking import create_chunks
from .providers import PdfExtractor, get_pdf_extractor

logger = logging.getLogger(__name__)


async def process_pdfs(
    resources: list[PdfResource],
    settings: Settings | None = None,
    *,
    assistant_id: str | None = None,
    extract_pdf: PdfExtractor | None = None,
    store_nodes: Callable[[list[TextNode]], None] | None = None,
) -> list[FileStatus]:
    settings = settings if settings is not None else Settings()
    statuses = []
    text_nodes_dict = {}
    all_text_nodes = []
    pending = []
    for resource in resources:
        status = file_status(resource["resource_id"], resource["file_name"])
        statuses.append(status)
        try:
            if not resource["file_name"].lower().endswith(".pdf"):
                raise ValueError("Unsupported file type")
            if extract_pdf is None:
                extract_pdf = get_pdf_extractor(settings)
            text_nodes = await extract_pdf(resource)
            for node in text_nodes:
                node.metadata["assistant_id"] = str(assistant_id or settings.faiss_persist_dir.name)
                node.metadata["source"] = resource["file_name"]
                node.metadata["file_type"] = "pdf"
            all_text_nodes.extend(text_nodes)
            text_nodes_dict[resource["file_name"]] = text_nodes
            pending.append(status)
        except Exception as exc:  # noqa: BLE001 - per-file error handling from the supplied pipeline
            status["error"] = str(exc)
            logger.warning("PDF processing failed for %s: %s", resource["file_name"], exc)
    if not all_text_nodes:
        return statuses
    try:
        chunks = await create_chunks(text_nodes_dict, settings=settings)
        if store_nodes is None:
            from ..storage import store_in_faiss

            store_nodes = partial(store_in_faiss, settings=settings)
        await asyncio.to_thread(store_nodes, chunks)
        for status in pending:
            status["success"] = True
    except Exception as exc:  # noqa: BLE001 - shared section/storage failure handling from the source
        for status in pending:
            status["error"] = str(exc)
        logger.warning("PDF processing failed: %s", exc)
    return statuses
