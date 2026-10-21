"""LlamaParse PDF extraction using the supplied page-to-node function."""

import tempfile
from pathlib import Path
from typing import List

from llama_index.core.schema import TextNode

from ...config import Settings
from ...models import PdfResource



def build_llamaparse_parser(settings: Settings):
    if not settings.llama_parse_api_key or not settings.llama_parse_api_key.get_secret_value():
        raise ValueError("LLAMA_PARSE_API_KEY is required for LlamaParse")
    from llama_cloud_services import LlamaParse

    return LlamaParse(
        api_key=settings.llama_parse_api_key.get_secret_value(),
        tier="agentic",
        version="latest",
        adaptive_long_table=True,
        outlined_table_extraction=True,
        output_tables_as_HTML=True,
        take_screenshot=False,
        invalidate_cache=False,
    )


async def extract_llamaparse_pdf(
    resource: PdfResource,
    settings: Settings,
    *,
    parser=None,
) -> list[TextNode]:
    parser = parser if parser is not None else build_llamaparse_parser(settings)
    # Close the file before passing its path to the parser (required on Windows).
    with tempfile.TemporaryDirectory(prefix="advanced-rag-") as directory:
        path = Path(directory) / "document.pdf"
        path.write_bytes(resource["data"])
        results = await parser.aparse([str(path)])
    text_nodes = []
    for result in results:
        text_nodes.extend(get_text_nodes_from_parse_result(
            result, resource["resource_id"], resource["file_name"],
        ))
    return text_nodes


def get_text_nodes_from_parse_result(result, resource_id: str, file_name: str = None) -> List[TextNode]:
    """Split parsed docs into nodes, by page."""
    nodes = []
    md_texts = [page.md for page in result.pages]
    paper_path = file_name if file_name else result.file_name

    for idx, md_text in enumerate(md_texts):
        chunk_metadata = {
            "page_num": idx + 1,
            "paper_path": paper_path,
            "resource_id": resource_id,
        }
        node = TextNode(text=md_text, metadata=chunk_metadata)
        nodes.append(node)
    return nodes
