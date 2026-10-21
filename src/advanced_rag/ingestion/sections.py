from __future__ import annotations
import json
from typing import List, Optional

from pydantic import BaseModel, Field
from llama_index.core.schema import TextNode
from llama_index.core.async_utils import run_jobs
from openai import AsyncOpenAI
from openai.types.responses import ResponseInputParam

from ..config import Settings, require_openai_key



class SectionOutput(BaseModel):
    """Metadata for a given section."""
    section_name: str = Field(
        ..., description="The current section number (e.g. section_name='3.2')"
    )
    section_title: str = Field(
        ..., description="The current section title (e.g. section_title='Experimental Results')"
    )
    start_page_number: int = Field(..., description="The start page number.")
    is_subsection: bool = Field(
        ..., description="True if it's a subsection (e.g. Section 3.2). False if not."
    )
    description: Optional[str] = Field(
        None, description="Extracted line from source text indicating this section."
    )

    def get_section_id(self):
        """Get section id."""
        return f"{self.section_name}: {self.section_title}"


class SectionsOutput(BaseModel):
    """A list of all sections."""
    sections: List[SectionOutput]


class ValidSections(BaseModel):
    """A list of indexes for valid sections."""
    valid_indexes: List[int] = Field(
        ..., description="List of valid section indexes. Do NOT include sections to remove."
    )



def annotate_chunks_with_sections(chunks: List[TextNode], sections: List[SectionOutput]):
    """Annotate each chunk with section metadata."""
    main_sections = [s for s in sections if not s.is_subsection]
    sub_sections = sections

    main_section_idx, sub_section_idx = 0, 0
    for idx, c in enumerate(chunks):
        cur_page = c.metadata["page_num"]
        while (
            main_section_idx + 1 < len(main_sections)
            and main_sections[main_section_idx + 1].start_page_number <= cur_page
        ):
            main_section_idx += 1
        while (
            sub_section_idx + 1 < len(sub_sections)
            and sub_sections[sub_section_idx + 1].start_page_number <= cur_page
        ):
            sub_section_idx += 1

        cur_main_section = main_sections[main_section_idx]
        cur_sub_section = sub_sections[sub_section_idx]

        c.metadata["section_id"] = cur_main_section.get_section_id()
        c.metadata["sub_section_id"] = cur_sub_section.get_section_id()


async def _aget_sections(doc_text: str, *, client: AsyncOpenAI, model: str) -> List[SectionOutput]:
    """Extract sections from document text using LLM."""
    system_prompt = """\
    You are an AI document assistant tasked with extracting section metadata from a document text. 
    
- Only extract metadata if the document text contains the beginning of a section.
- Extract section_name, section_title, start page number, description.
- A valid section MUST begin with a hashtag (#) and have a number (e.g. "1 Introduction").
- You can extract multiple sections if there are multiple on the page. 
- If there are no sections, do NOT extract any.
- A Figure or Table does NOT count as a section.
    """
    messages: ResponseInputParam = [
        {"content": system_prompt, "role": "system"},
        {"content": f"Document text: {doc_text}", "role": "user"},
    ]
    result = await client.responses.parse(model=model, input=messages, text_format=SectionsOutput)
    if result.output_parsed is None:
        raise ValueError("لم يستطع مودل المحادثة تحديد أقسام PDF. راجع المودل من الإعدادات.")
    return result.output_parsed.sections


async def _arefine_sections(sections: List[SectionOutput], *, client: AsyncOpenAI, model: str) -> List[SectionOutput]:
    """Refine sections by removing invalid ones."""
    system_prompt = """\
    You are an AI review assistant tasked with reviewing extracted sections from a document.

    Review the list of sections with indexes. The sections may be incorrect:
    - False positive sections wrongly extracted
    - Sections incorrectly marked as subsections and vice-versa

    Return the list of indexes that are valid. Do NOT include indexes to be removed.
    """
    section_texts = "\n".join(
        [f"{idx}: {json.dumps(s.model_dump())}" for idx, s in enumerate(sections)]
    )

    messages: ResponseInputParam = [
        {"content": system_prompt, "role": "system"},
        {"content": f"Sections in text:\n\n{section_texts}", "role": "user"},
    ]

    result = await client.responses.parse(model=model, input=messages, text_format=ValidSections)
    if result.output_parsed is None:
        raise ValueError("لم يكتمل التحقق من أقسام PDF. حاول مجددًا.")
    valid_indexes = result.output_parsed.valid_indexes

    new_sections = [s for idx, s in enumerate(sections) if idx in valid_indexes]
    return new_sections


async def create_sections(text_nodes_dict: dict, *, settings: Settings) -> dict:
    """Create sections dictionary from text nodes."""
    sections_dict = {}
    async with AsyncOpenAI(api_key=require_openai_key(settings), timeout=60, max_retries=1) as client:
        for paper_path, text_nodes in text_nodes_dict.items():
            tasks = [_aget_sections(n.get_content(metadata_mode="all"), client=client, model=settings.agent_model) for n in text_nodes]
            async_results = await run_jobs(tasks, workers=8, show_progress=True)
            all_sections = [s for r in async_results for s in r]
            if all_sections:
                all_sections = await _arefine_sections(all_sections, client=client, model=settings.agent_model)
            sections_dict[paper_path] = all_sections
    return sections_dict
