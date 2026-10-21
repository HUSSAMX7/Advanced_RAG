"""Prepare PDF chunks by annotating pages with sections, then splitting sentences."""

from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode

from ..config import Settings
from .sections import annotate_chunks_with_sections, create_sections


async def create_chunks(
    text_nodes_dict: dict[str, list[TextNode]], *, settings: Settings | None = None
) -> list[TextNode]:
    """Annotate the supplied pages in place and return chunks with their metadata."""
    settings = settings or Settings()
    sections_dict = await create_sections(text_nodes_dict, settings=settings)
    for paper_path, text_nodes in text_nodes_dict.items():
        if sections_dict.get(paper_path):
            annotate_chunks_with_sections(text_nodes, sections_dict[paper_path])
        else:
            default_section_id = f"0: {paper_path}"
            for node in text_nodes:
                node.metadata["section_id"] = default_section_id
                node.metadata["sub_section_id"] = default_section_id
    all_text_nodes = [node for nodes in text_nodes_dict.values() for node in nodes]
    splitter = SentenceSplitter(chunk_size=1024, chunk_overlap=50)
    chunks = splitter(all_text_nodes)
    if any(not isinstance(chunk, TextNode) for chunk in chunks):
        raise ValueError("Document splitting returned a non-text chunk")
    return [chunk for chunk in chunks if isinstance(chunk, TextNode)]
