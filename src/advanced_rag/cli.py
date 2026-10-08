"""Run the supplied PDF processing flow from this project."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

from dotenv import load_dotenv

from .config import Settings
from .ingestion.pipeline import process_pdfs
from .models import file_status, resource_from_path

logger = logging.getLogger(__name__)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Extract and chunk PDF files for RAG")
    command.add_argument("files", nargs="+", type=Path, help="PDF file paths")
    command.add_argument("--provider", choices=["llamaparse", "lightonocr"])
    command.add_argument(
        "--persist-dir", type=Path, help="FAISS storage directory (overrides .env)"
    )
    command.add_argument("--assistant-id", help="Optional assistant metadata")
    return command


async def _run(args) -> int:
    load_dotenv()
    overrides = {}
    if args.provider:
        overrides["pdf_provider"] = args.provider
    if args.persist_dir:
        overrides["faiss_persist_dir"] = args.persist_dir
    settings = Settings(**overrides)
    resources = []
    invalid = []
    for path in args.files:
        try:
            resources.append(resource_from_path(path))
        except (ValueError, OSError) as exc:
            invalid.append(file_status(str(path), path.name, error=str(exc)))
    result = await process_pdfs(
        resources,
        settings,
        assistant_id=args.assistant_id,
    )
    statuses = [*invalid, *result]
    print(json.dumps(statuses, ensure_ascii=False, indent=2))
    return 0 if all(status["success"] for status in statuses) else 1


def main() -> None:
    args = parser().parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    try:
        exit_code = asyncio.run(_run(args))
    except (ValueError, OSError) as exc:
        logger.error("%s", exc)
        exit_code = 1
    raise SystemExit(exit_code)
