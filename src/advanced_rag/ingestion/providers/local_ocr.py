"""Run local PDF OCR on demand in a cancellable, short-lived CPU process."""

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

from ...config import Settings
from ...local_models import inference_lock
from ...retrieval.reranking import release_reranker


def _worker_command(directory: Path, settings: Settings):
    return [sys.executable, str(Path(__file__).with_name("ocr_worker.py")), str(directory)]


def _kill_worker(process):
    if process.poll() is not None:
        return
    if os.name == "nt":
        # The venv launcher can own a child interpreter on Windows.
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=0x08000000,
            check=False,
        )
    else:
        process.kill()
    process.wait()


def _read_pages(directory: Path):
    try:
        result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(
            "توقف LightOnOCR المحلي قبل اكتمال استخراج الملف. تحقق من الذاكرة والمودل."
        ) from exc
    if result.get("error") == "truncated":
        raise ValueError("تجاوز نص إحدى الصفحات حد LightOnOCR؛ لم يتم تدريب الملف بنص ناقص.")
    if result.get("error"):
        raise ValueError(
            "فشل LightOnOCR محليًا. تحقق من اكتمال تنزيل المودل وتوفر ذاكرة كافية، ثم أعد المحاولة."
        )
    pages = result.get("pages", [])
    count = result.get("page_count", 0)
    if (
        not isinstance(count, int)
        or count <= 0
        or len(pages) != count
        or any(
            not isinstance(page, list)
            or len(page) != 2
            or page[0] != index
            or not isinstance(page[1], str)
            for index, page in enumerate(pages)
        )
    ):
        raise ValueError("لم يكتمل استخراج كل صفحات الملف؛ لم يتم حفظ تدريب ناقص.")
    return [(index, text) for index, text in pages]


def _run_worker(data, settings, progress, cancelled):
    while not inference_lock.acquire(timeout=0.1):
        if cancelled.is_set():
            return []
    try:
        if cancelled.is_set():
            return []
        release_reranker()
        with tempfile.TemporaryDirectory(prefix="rag-local-ocr-") as name:
            directory = Path(name)
            (directory / "input.pdf").write_bytes(data)
            (directory / "config.json").write_text(
                json.dumps(
                    {
                        "model": settings.lightonocr_model,
                        "dpi": settings.lightonocr_dpi,
                        "max_tokens": settings.lightonocr_max_tokens,
                    }
                ),
                encoding="utf-8",
            )
            progress("preparing_ocr")
            environment = os.environ.copy()
            environment["HF_HUB_DISABLE_XET"] = "1"
            for key in ("OPENAI_API_KEY", "LLAMA_PARSE_API_KEY", "LLAMA_CLOUD_API_KEY"):
                environment.pop(key, None)
            with (directory / "worker.log").open("wb") as log:
                process = subprocess.Popen(
                    _worker_command(directory, settings),
                    env=environment,
                    stdout=log,
                    stderr=log,
                    **({"creationflags": 0x08000000} if os.name == "nt" else {}),
                )
                last_status = None
                deadline = time.monotonic() + settings.lightonocr_local_timeout_seconds
                try:
                    while process.poll() is None:
                        if cancelled.wait(0.1):
                            return []
                        try:
                            status = (directory / "status.json").read_text(encoding="utf-8")
                        except OSError:
                            status = None
                        if status and status != last_status:
                            last_status = status
                            deadline = time.monotonic() + settings.lightonocr_local_timeout_seconds
                            state = json.loads(status)
                            if state.get("page"):
                                progress(f"ocr_page:{state['page']}:{state['total']}")
                        if time.monotonic() > deadline:
                            raise ValueError(
                                "انتهت مهلة LightOnOCR المحلي. حاول ملفًا أصغر أو مزوّد API من الإعدادات."
                            )
                    return _read_pages(directory)
                finally:
                    _kill_worker(process)
    finally:
        inference_lock.release()


async def extract_local_pdf(pdf_bytes: bytes, settings: Settings, progress=lambda stage: None):
    cancelled = threading.Event()
    task = asyncio.create_task(
        asyncio.to_thread(_run_worker, pdf_bytes, settings, progress, cancelled)
    )
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        cancelled.set()
        await asyncio.shield(task)
        raise
