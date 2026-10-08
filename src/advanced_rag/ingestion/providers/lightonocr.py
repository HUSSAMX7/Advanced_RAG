"""
LightOnOCR provider for PDF processing.

Renders PDF pages to images, sends them to a vLLM endpoint running
LightOnOCR-2-1B, and returns LlamaIndex TextNodes with the same
metadata schema as the LlamaParse path.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import re
from html.parser import HTMLParser
from typing import List

import httpx
import pypdfium2 as pdfium
from llama_index.core.schema import TextNode

logger = logging.getLogger("lightonocr")


# ============================================================================
# PDF → base64 JPEG rendering
# ============================================================================

def render_pages(pdf_bytes: bytes, dpi: int = 200) -> list[str]:
    """Render every page of a PDF to a base64-encoded JPEG string."""
    pdf = pdfium.PdfDocument(io.BytesIO(pdf_bytes))
    pages: list[str] = []
    for i in range(len(pdf)):
        page = pdf[i]
        img = page.render(scale=dpi / 72).to_pil()
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        pages.append(base64.b64encode(buf.getvalue()).decode())
    return pages


# ============================================================================
# Async OCR via vLLM endpoint
# ============================================================================

async def _ocr_page(
    client: httpx.AsyncClient,
    b64_image: str,
    page_num: int,
    semaphore: asyncio.Semaphore,
    config: dict,
) -> tuple[int, str]:
    """OCR a single page image through the vLLM chat-completions endpoint."""
    async with semaphore:
        payload = {
            "model": config.get("model", "lightonai/LightOnOCR-2-1B"),
            "max_tokens": config.get("max_tokens", 4096),
            "temperature": config.get("temperature", 0.0),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64_image}",
                            },
                        }
                    ],
                }
            ],
        }
        resp = await client.post(config["url"], json=payload)
        resp.raise_for_status()
        data = resp.json()
        text = data["choices"][0]["message"]["content"]
        logger.info("Page %d: %d chars", page_num + 1, len(text))
        return page_num, text


async def ocr_pdf(pdf_bytes: bytes, config: dict) -> list[tuple[int, str]]:
    """Render + OCR all pages concurrently. Returns sorted (page_idx, text)."""
    dpi = config.get("dpi", 200)
    concurrency = config.get("concurrency", 64)
    timeout_sec = config.get("timeout_seconds", 300)

    logger.info("Rendering pages at %d DPI ...", dpi)
    b64_pages = await asyncio.to_thread(render_pages, pdf_bytes, dpi)
    logger.info("Rendered %d pages", len(b64_pages))

    semaphore = asyncio.Semaphore(concurrency)
    timeout = httpx.Timeout(float(timeout_sec), connect=30.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        tasks = [
            _ocr_page(client, img, i, semaphore, config)
            for i, img in enumerate(b64_pages)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    successful: list[tuple[int, str]] = []
    for r in results:
        if isinstance(r, Exception):
            logger.warning("OCR page failed: %s", r)
        else:
            successful.append(r)

    successful.sort(key=lambda x: x[0])
    return successful


# ============================================================================
# Post-processing (adapted from postprocess_ocr.py)
# ============================================================================

ARABIC_OCR_CORRECTIONS: dict[str, str] = {
    "نوفير": "توفير",
    "نوصية": "توصية",
    "نوضيح": "توضيح",
    "نوظيف": "توظيف",
    "نوجهات": "توجهات",
    "دفائق": "دقائق",
}


class _TableParser(HTMLParser):
    """Minimal HTML table parser that extracts rows of cell texts."""

    def __init__(self):
        super().__init__()
        self._rows: list[list[str]] = []
        self._current_row: list[str] | None = None
        self._current_cell: list[str] | None = None
        self._in_cell = False
        self._has_thead = False
        self._thead_row_count = 0
        self._in_thead = False

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == "thead":
            self._in_thead = True
            self._has_thead = True
        elif tag == "tbody":
            self._in_thead = False
        elif tag == "tr":
            self._current_row = []
        elif tag in ("td", "th"):
            self._current_cell = []
            self._in_cell = True

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "thead":
            self._in_thead = False
        if tag in ("td", "th") and self._current_cell is not None:
            text = "".join(self._current_cell).strip()
            text = re.sub(r"\s+", " ", text)
            if self._current_row is not None:
                self._current_row.append(text)
            self._current_cell = None
            self._in_cell = False
        elif tag == "tr" and self._current_row is not None:
            self._rows.append(self._current_row)
            if self._in_thead:
                self._thead_row_count += 1
            self._current_row = None

    def handle_data(self, data):
        if self._in_cell and self._current_cell is not None:
            self._current_cell.append(data)

    @property
    def rows(self):
        return self._rows

    @property
    def header_rows(self):
        return self._thead_row_count if self._has_thead else 0


def _html_table_to_markdown(html: str) -> str:
    parser = _TableParser()
    try:
        parser.feed(html)
    except Exception:
        return html

    rows = parser.rows
    if not rows:
        return html

    max_cols = max(len(r) for r in rows)
    if max_cols == 0:
        return html

    for row in rows:
        while len(row) < max_cols:
            row.append("")

    lines: list[str] = []
    header_count = parser.header_rows if parser.header_rows > 0 else 1

    for i, row in enumerate(rows):
        line = "| " + " | ".join(row) + " |"
        lines.append(line)
        if i == header_count - 1:
            sep = "| " + " | ".join("---" for _ in range(max_cols)) + " |"
            lines.append(sep)

    return "\n".join(lines)


def convert_html_tables(text: str) -> tuple[str, int]:
    pattern = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
    count = 0

    def _replace(m: re.Match) -> str:
        nonlocal count
        count += 1
        return _html_table_to_markdown(m.group(0))

    result = pattern.sub(_replace, text)
    return result, count


def collapse_repetition_loops(text: str) -> tuple[str, int]:
    total_removed = 0

    # Pass 1: consecutive identical non-blank lines
    lines = text.split("\n")
    result: list[str] = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            result.append(lines[i])
            i += 1
            continue
        j = i + 1
        while j < len(lines) and lines[j].strip() == stripped:
            j += 1
        run_length = j - i
        if run_length >= 3:
            result.append(lines[i])
            total_removed += run_length - 1
        else:
            for k in range(i, j):
                result.append(lines[k])
        i = j

    # Pass 2: blank-line-separated repetitions
    lines = result
    result = []
    i = 0
    while i < len(lines):
        stripped = lines[i].strip()
        if not stripped:
            result.append(lines[i])
            i += 1
            continue
        run_indices = [i]
        j = i + 1
        while j < len(lines):
            if lines[j].strip() == "":
                if j + 1 < len(lines) and lines[j + 1].strip() == stripped:
                    run_indices.append(j + 1)
                    j = j + 2
                else:
                    break
            else:
                break
        if len(run_indices) >= 3:
            result.append(lines[run_indices[0]])
            result.append("")
            total_removed += len(run_indices) - 1
            i = j
        else:
            result.append(lines[i])
            i += 1

    return "\n".join(result), total_removed


def remove_hallucination_notes(text: str) -> tuple[str, int]:
    pattern = re.compile(
        r"\n*^Note: The image .*?(?=\n\n|\n---|\Z)",
        re.MULTILINE | re.DOTALL,
    )
    text, count = pattern.subn("", text)
    return text, count


def apply_arabic_corrections(text: str) -> tuple[str, int]:
    total = 0
    for wrong, correct in ARABIC_OCR_CORRECTIONS.items():
        text, n = re.subn(re.escape(wrong), correct, text)
        total += n
    return text, total


def normalize_whitespace(text: str) -> str:
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"[ \t]+$", "", text, flags=re.MULTILINE)
    text = text.strip() + "\n"
    return text


def postprocess_page(text: str) -> str:
    """Run the per-page cleaning pipeline."""
    text, _ = collapse_repetition_loops(text)
    text, _ = remove_hallucination_notes(text)
    text, _ = convert_html_tables(text)
    text, _ = apply_arabic_corrections(text)
    text = normalize_whitespace(text)
    return text


# ============================================================================
# Main entry point — produces TextNodes matching LlamaParse schema
# ============================================================================

async def get_text_nodes_from_lightonocr(
    pdf_bytes: bytes,
    resource_id: str,
    file_name: str,
    config: dict,
) -> List[TextNode]:
    """OCR a PDF via LightOnOCR and return TextNodes with identical metadata
    to the LlamaParse path (page_num, paper_path, resource_id)."""

    page_results = await ocr_pdf(pdf_bytes, config)

    do_postprocess = config.get("postprocess", True)
    nodes: List[TextNode] = []

    for page_idx, md_text in page_results:
        if do_postprocess:
            md_text = postprocess_page(md_text)

        # Skip effectively-empty pages
        meaningful = re.sub(r"[#*_\-\s\n>`|]", "", md_text)
        if len(meaningful) < 20:
            logger.info("Skipping empty page %d", page_idx + 1)
            continue

        node = TextNode(
            text=md_text,
            metadata={
                "page_num": page_idx + 1,
                "paper_path": file_name,
                "resource_id": resource_id,
            },
        )
        nodes.append(node)

    logger.info("Created %d text nodes from %s", len(nodes), file_name)
    return nodes
