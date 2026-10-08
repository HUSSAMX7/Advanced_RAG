import asyncio
import sys
import time

import pytest

from advanced_rag.config import Settings
from advanced_rag.ingestion.providers.local_ocr import extract_local_pdf


def worker(monkeypatch, tmp_path, source):
    script = tmp_path / "worker.py"
    script.write_text("import pathlib,sys,json,time\nb=pathlib.Path(sys.argv[1])\n" + source)
    monkeypatch.setattr(
        "advanced_rag.ingestion.providers.local_ocr._worker_command",
        lambda directory, settings: [sys.executable, str(script), str(directory)],
    )


def settings():
    return Settings(_env_file=None, pdf_provider="lightonocr", lightonocr_local=True)


def test_local_worker_starts_on_extraction_and_preserves_every_page(monkeypatch, tmp_path):
    worker(
        monkeypatch,
        tmp_path,
        "(b/'result.json').write_text(json.dumps({'pages':[[0,'First page with enough invoice content'],[1,'Second page contains total 120']], 'page_count':2}))\n",
    )
    stages = []
    pages = asyncio.run(extract_local_pdf(b"pdf", settings(), stages.append))
    assert pages == [
        (0, "First page with enough invoice content"),
        (1, "Second page contains total 120"),
    ]
    assert stages[0] == "preparing_ocr"


def test_partial_local_result_fails_instead_of_training_missing_pages(monkeypatch, tmp_path):
    worker(
        monkeypatch,
        tmp_path,
        "(b/'result.json').write_text(json.dumps({'pages':[[0,'only one page']], 'page_count':2}))\n",
    )
    with pytest.raises(ValueError, match="كل صفحات"):
        asyncio.run(extract_local_pdf(b"pdf", settings()))


def test_local_worker_errors_and_timeouts_are_visible(monkeypatch, tmp_path):
    worker(monkeypatch, tmp_path, "(b/'result.json').write_text(json.dumps({'error':'model'}))\n")
    with pytest.raises(ValueError, match="LightOnOCR"):
        asyncio.run(extract_local_pdf(b"pdf", settings()))
    worker(monkeypatch, tmp_path, "time.sleep(20)\n")
    started = time.monotonic()
    with pytest.raises(ValueError, match="مهلة"):
        asyncio.run(
            extract_local_pdf(
                b"pdf", settings().model_copy(update={"lightonocr_local_timeout_seconds": 0.3})
            )
        )
    assert time.monotonic() - started < 5


def test_cancelled_local_worker_is_killed_before_it_can_finish(monkeypatch, tmp_path):
    finished = tmp_path / "finished"
    ready = tmp_path / "ready"
    worker(
        monkeypatch,
        tmp_path,
        f"pathlib.Path({str(ready)!r}).touch()\ntime.sleep(1)\npathlib.Path({str(finished)!r}).touch()\n",
    )

    async def run():
        task = asyncio.create_task(extract_local_pdf(b"pdf", settings()))
        for _ in range(200):
            if ready.exists():
                break
            await asyncio.sleep(0.01)
        assert ready.exists()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(1.1)

    asyncio.run(run())
    assert not finished.exists()
