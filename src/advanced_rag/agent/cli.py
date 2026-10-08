"""Interactive or one-question chat against a locally saved FAISS index."""

import argparse
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAIError

from ..config import Settings, require_openai_key
from ..retrieval import load_search_context
from .chat import ask_agent
from .sessions import load_session
from .types import AgentAnswer


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Ask questions about indexed documents")
    command.add_argument("--question", help="Ask one question instead of starting interactive chat")
    command.add_argument("--session", help="Resume a saved session UUID")
    command.add_argument("--persist-dir", type=Path, help="FAISS index directory")
    command.add_argument("--sessions-dir", type=Path, help="Directory for local chat sessions")
    return command


def _print_answer(result: AgentAnswer) -> None:
    print(result["answer"])
    for source in result["sources"]:
        metadata = source["metadata"]
        name = metadata.get("source") or metadata.get("paper_path") or source["chunk_id"]
        page = metadata.get("page_num", "?")
        print(f"[{source['citation']}] {name} — page {page}")
    print(f"Session: {result['session_id']}")


async def _run(args: argparse.Namespace) -> int:
    load_dotenv()
    overrides = {}
    if args.persist_dir is not None:
        overrides["faiss_persist_dir"] = args.persist_dir
    if args.sessions_dir is not None:
        overrides["chat_sessions_dir"] = args.sessions_dir
    settings = Settings(**overrides)
    # Validate an explicit session before loading the index or making any API request.
    if args.session is not None:
        load_session(args.session, settings=settings)
    context = load_search_context(settings)
    async with AsyncOpenAI(
        api_key=require_openai_key(settings), timeout=60.0, max_retries=2
    ) as client:
        session_id = args.session
        if args.question is not None:
            result = await ask_agent(
                args.question,
                context=context,
                client=client,
                settings=settings,
                session_id=session_id,
            )
            _print_answer(result)
            return 0
        print("Ask about your documents. Type /exit to quit.")
        while True:
            try:
                question = input("You: ").strip()
            except EOFError:
                return 0
            if question.lower() in {"/exit", "/quit"}:
                return 0
            if not question:
                continue
            try:
                result = await ask_agent(
                    question,
                    context=context,
                    client=client,
                    settings=settings,
                    session_id=session_id,
                )
            except (OpenAIError, OSError, ValueError, RuntimeError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                continue
            session_id = result["session_id"]
            _print_answer(result)


def main() -> None:
    args = parser().parse_args()
    try:
        exit_code = asyncio.run(_run(args))
    except KeyboardInterrupt:
        exit_code = 130
    except (OpenAIError, OSError, ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        exit_code = 1
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
