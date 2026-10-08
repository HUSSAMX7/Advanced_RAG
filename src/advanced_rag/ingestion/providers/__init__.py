"""Select an extraction function and reuse library clients across a batch."""

from collections.abc import Awaitable, Callable
from functools import partial

from llama_index.core.schema import TextNode

from ...config import Settings
from ...models import PdfResource

PdfExtractor = Callable[[PdfResource], Awaitable[list[TextNode]]]


def get_pdf_extractor(settings: Settings, *, progress=lambda stage: None) -> PdfExtractor:
    if settings.pdf_provider == "llamaparse":
        from .llamaparse import build_llamaparse_parser, extract_llamaparse_pdf

        return partial(
            extract_llamaparse_pdf, settings=settings, parser=build_llamaparse_parser(settings)
        )
    from .lightonocr import get_text_nodes_from_lightonocr, pages_to_nodes

    async def extract_lightonocr_pdf(resource: PdfResource) -> list[TextNode]:
        if settings.lightonocr_local:
            from .local_ocr import extract_local_pdf

            pages = await extract_local_pdf(resource["data"], settings, progress)
            return pages_to_nodes(pages, resource["resource_id"], resource["file_name"], settings.lightonocr_postprocess)
        if not settings.lightonocr_url:
            raise ValueError("حدد عنوان خادم LightOnOCR أو استخدم الوضع المحلي من صفحة الإعدادات.")
        return await get_text_nodes_from_lightonocr(
            pdf_bytes=resource["data"],
            resource_id=resource["resource_id"],
            file_name=resource["file_name"],
            config={
                "url": settings.lightonocr_url,
                "model": settings.lightonocr_model,
                "dpi": settings.lightonocr_dpi,
                "concurrency": settings.lightonocr_concurrency,
                "max_tokens": settings.lightonocr_max_tokens,
                "temperature": 0.0,
                "timeout_seconds": settings.lightonocr_timeout_seconds,
                "postprocess": settings.lightonocr_postprocess,
            },
        )

    return extract_lightonocr_pdf
