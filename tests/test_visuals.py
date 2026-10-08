import asyncio
import base64
import io
import json
from uuid import uuid4

import httpx
import pymupdf
import pytest
from conftest import api_client, response_payload
from fastapi.testclient import TestClient
from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import TextNode
from PIL import Image
from pydantic import SecretStr
from test_agent import tool_response
from test_web import wait_status, web_settings

from advanced_rag.agent import ask_agent
from advanced_rag.agent.sessions import load_session
from advanced_rag.ingestion.documents import prepare_document
from advanced_rag.retrieval import load_search_context, search_documents
from advanced_rag.storage import read_index_nodes, store_in_faiss
from advanced_rag.visuals import enrich_pdf_chunks, evidence_text, image_path, prune_images
from advanced_rag.web.app import create_app
from advanced_rag.web.registry import Registry

CAPTION = "Figure 1: Engine assembly"
DESCRIPTION = "RotorQ scarlet machinery رسم المحرك الأحمر"


def pdf_resource(*, vector=False, scan=False):
    document = pymupdf.open()
    page = document.new_page(width=500, height=600)
    page.insert_text((60, 115), CAPTION)
    page.insert_text((60, 450), "The diagram explains the engine components.")
    if vector:
        page.draw_rect(pymupdf.Rect(60, 140, 260, 300), color=(1, 0, 0), fill=(1, 0, 0))
    else:
        output = io.BytesIO()
        Image.new("RGB", (200, 160), "red").save(output, format="PNG")
        page.insert_image(pymupdf.Rect(60, 140, 260, 300), stream=output.getvalue())
    if scan:
        image = page.get_pixmap().tobytes("png")
        document.close()
        document = pymupdf.open()
        page = document.new_page(width=500, height=600)
        page.insert_image(page.rect, stream=image)
    data = document.tobytes()
    document.close()
    return {
        "resource_id": str(uuid4()),
        "file_name": "engine.pdf",
        "data": data,
        "include_images": True,
    }


def page_nodes(resource):
    with pymupdf.open(stream=resource["data"], filetype="pdf") as document:
        text = document[0].get_text()
    return [
        TextNode(
            text=text,
            metadata={
                "resource_id": resource["resource_id"],
                "source": resource["file_name"],
                "page_num": 1,
            },
        )
    ]


def caption_response(request, *, anchor=CAPTION, fail=False):
    if fail:
        return httpx.Response(400, json={"error": {"message": "Vision unavailable"}})
    body = json.loads(request.content)
    assert body["store"] is False
    content = body["input"][0]["content"]
    ids = [
        item["text"].split(": ", 1)[1]
        for item in content
        if item["type"] == "input_text" and item["text"].startswith("Candidate ID:")
    ]
    assert ids
    assert any(item["type"] == "input_image" for item in content)
    return httpx.Response(
        200,
        json=response_payload(
            {
                "images": [
                    {"id": image_id, "description": DESCRIPTION, "anchor_text": anchor}
                    for image_id in ids
                ]
            }
        ),
    )


async def enrich(resource, settings, *, anchor=CAPTION, fail=False, pages=None):
    pages = page_nodes(resource) if pages is None else pages
    chunks = [node.model_copy(deep=True) for node in pages if node.text.strip()]
    async with api_client(
        lambda request: caption_response(request, anchor=anchor, fail=fail)
    ) as client:
        return await enrich_pdf_chunks(resource, pages, chunks, settings, client=client)


@pytest.mark.parametrize("vector", [False, True])
def test_pdf_geometry_links_original_figure_and_description_search_preserves_evidence(
    tmp_path, local_reranker, vector
):
    resource = pdf_resource(vector=vector)
    settings = web_settings(tmp_path).model_copy(update={"rerank_model": local_reranker.model_name})
    nodes = asyncio.run(enrich(resource, settings))
    assert len(nodes) == 2
    original, description = nodes
    assert original.text == page_nodes(resource)[0].text
    assert description.text == DESCRIPTION
    assert description.metadata["images"][0]["kind"] == "figure"
    image_id = description.metadata["images"][0]["id"]
    with Image.open(image_path(settings, image_id)) as image:
        assert image.getpixel((image.width // 2, image.height // 2))[0] > 240
    embedding = MockEmbedding(embed_dim=2)
    store_in_faiss(nodes, settings, embed_model=embedding)
    context = load_search_context(settings, embed_model=embedding)
    # A term that occurs only in the generated description must find the visual.
    from advanced_rag.retrieval import search

    async def rank(query, candidates, *, settings):
        assert any(DESCRIPTION in hit["text"] for hit in candidates)
        return sorted(candidates, key=lambda hit: hit["chunk_id"] != description.node_id)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(search, "rerank_chunks", rank)
        hits = asyncio.run(search_documents("RotorQ", context=context, settings=settings))
    assert hits[0]["chunk_id"] == description.node_id
    assert hits[0]["text"] == original.text
    assert DESCRIPTION not in json.dumps(hits, ensure_ascii=False)
    assert "original_text" not in hits[0]["metadata"]
    prune_images(settings, nodes)
    assert [path.stem for path in (settings.web_data_dir / "images").glob("*.jpg")] == [image_id]


@pytest.mark.parametrize(
    "anchor", ["", "A fabricated caption", "The diagram explains the engine components."]
)
def test_unclear_or_distant_anchor_sends_full_page(tmp_path, anchor):
    settings = web_settings(tmp_path)
    nodes = asyncio.run(enrich(pdf_resource(), settings, anchor=anchor))
    assert all(node.metadata["images"][0]["kind"] == "page" for node in nodes)
    with Image.open(image_path(settings, nodes[0].metadata["images"][0]["id"])) as image:
        assert image.size == (1000, 1200)


def test_scan_and_image_only_pdf_remain_searchable_as_page_evidence(tmp_path):
    settings = web_settings(tmp_path)
    resource = pdf_resource(scan=True)
    nodes = asyncio.run(enrich(resource, settings, anchor="", pages=[]))
    assert len(nodes) == 1
    assert nodes[0].text == DESCRIPTION
    assert evidence_text(nodes[0]) == ""
    assert nodes[0].metadata["images"][0]["kind"] == "page"


def test_rotated_pdf_visuals_preserve_the_full_displayed_page(tmp_path):
    settings = web_settings(tmp_path)
    resource = pdf_resource()
    with pymupdf.open(stream=resource["data"], filetype="pdf") as document:
        document[0].set_rotation(90)
        resource["data"] = document.tobytes()
    nodes = asyncio.run(enrich(resource, settings))
    visual = nodes[0].metadata["images"][0]
    assert visual["kind"] == "page"
    with Image.open(image_path(settings, visual["id"])) as image:
        assert image.size == (1200, 1000)
        assert (
            sum(
                count
                for count, color in image.getcolors(maxcolors=2_000_000)
                if color[0] > 240 and color[1] < 10 and color[2] < 10
            )
            > 10_000
        )


@pytest.mark.parametrize("crossed", [False, True])
def test_two_columns_do_not_link_a_figure_to_the_other_columns_caption(tmp_path, crossed):
    settings = web_settings(tmp_path)
    document = pymupdf.open()
    page = document.new_page(width=600, height=600)
    captions = ["Figure 1: Engine assembly", "Figure 2: Brake assembly"]
    for x, caption, color in zip([50, 350], captions, ["red", "blue"], strict=True):
        page.insert_text((x, 100), caption)
        data = io.BytesIO()
        Image.new("RGB", (180, 150), color).save(data, format="PNG")
        page.insert_image(pymupdf.Rect(x, 120, x + 180, 270), stream=data.getvalue())
    resource = {
        "resource_id": str(uuid4()),
        "file_name": "two-columns.pdf",
        "data": document.tobytes(),
    }
    document.close()
    pages = [TextNode(text="\n".join(captions), metadata={"page_num": 1})]
    chunks = [
        TextNode(text=caption, metadata={"page_num": 1, "resource_id": resource["resource_id"]})
        for caption in captions
    ]

    def respond(request):
        body = json.loads(request.content)
        ids = body["text"]["format"]["schema"]["properties"]["images"]["items"]["properties"]["id"][
            "enum"
        ]
        anchors = list(reversed(captions)) if crossed else captions
        return httpx.Response(
            200,
            json=response_payload(
                {
                    "images": [
                        {"id": image_id, "description": caption, "anchor_text": caption}
                        for image_id, caption in zip(ids, anchors, strict=True)
                    ]
                }
            ),
        )

    async def run():
        async with api_client(respond) as client:
            return await enrich_pdf_chunks(resource, pages, chunks, settings, client=client)

    nodes = asyncio.run(run())
    if crossed:
        assert all(node.metadata["images"][0]["kind"] == "page" for node in nodes)
    else:
        assert chunks[0].metadata["images"] != chunks[1].metadata["images"]
        for chunk, expected in zip(chunks, [0, 2], strict=True):
            with Image.open(image_path(settings, chunk.metadata["images"][0]["id"])) as image:
                assert image.getpixel((image.width // 2, image.height // 2))[expected] > 240


def test_database_upgrade_keeps_existing_files_without_visual_opt_in(tmp_path):
    import sqlite3

    settings = web_settings(tmp_path)
    settings.web_data_dir.mkdir(parents=True)
    file_id = str(uuid4())
    with sqlite3.connect(settings.web_data_dir / "library.sqlite3") as connection:
        connection.execute("""CREATE TABLE files (
            id TEXT PRIMARY KEY, name TEXT, size INTEGER, type TEXT, status TEXT,
            stage TEXT, error TEXT, original TEXT, intent TEXT, chunks INTEGER,
            created_at TEXT, updated_at TEXT)""")
        connection.execute(
            """INSERT INTO files VALUES (?, 'old.pdf', 1, 'pdf', 'untrained',
                           NULL, NULL, NULL, NULL, 0, '', '')""",
            (file_id,),
        )
    registry = Registry(settings.web_data_dir)
    assert registry.get(file_id)["image_support"] == 0
    assert registry.public(registry.get(file_id))["name"] == "old.pdf"


def test_caption_failure_keeps_text_and_original_page_with_warning(tmp_path):
    settings = web_settings(tmp_path)
    resource = pdf_resource()
    nodes = asyncio.run(enrich(resource, settings, fail=True))
    assert nodes[0].text == page_nodes(resource)[0].text
    assert all("visual_warning" in node.metadata for node in nodes)
    assert nodes[1].metadata["images"][0]["kind"] == "page"
    assert image_path(settings, nodes[1].metadata["images"][0]["id"]).exists()


def test_crop_failure_falls_back_to_page_and_keeps_other_evidence(tmp_path, monkeypatch):
    from advanced_rag import visuals

    save = visuals._save

    def failing_crop(page, rect, settings, created):
        if rect != page.rect:
            raise ValueError("Damaged crop")
        return save(page, rect, settings, created)

    monkeypatch.setattr(visuals, "_save", failing_crop)
    settings = web_settings(tmp_path)
    nodes = asyncio.run(enrich(pdf_resource(), settings))
    assert all(node.metadata["images"][0]["kind"] == "page" for node in nodes)
    assert "visual_warning" in nodes[0].metadata


def test_cancellation_during_description_removes_unpublished_assets(tmp_path):
    settings = web_settings(tmp_path)
    resource = pdf_resource()

    async def run():
        started = asyncio.Event()

        async def respond(request):
            started.set()
            await asyncio.Event().wait()

        async with api_client(respond) as client:
            nodes = page_nodes(resource)
            task = asyncio.create_task(
                enrich_pdf_chunks(resource, nodes, nodes, settings, client=client)
            )
            await started.wait()
            assert list((settings.web_data_dir / "images").glob("*.jpg"))
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(run())
    assert not list((settings.web_data_dir / "images").glob("*.jpg"))


def test_agent_receives_real_image_bytes_without_search_description_and_deduplicates(
    tmp_path, local_reranker
):
    settings = web_settings(tmp_path).model_copy(update={"rerank_model": local_reranker.model_name})
    nodes = asyncio.run(enrich(pdf_resource(), settings))
    embedding = MockEmbedding(embed_dim=2)
    store_in_faiss(nodes, settings, embed_model=embedding)
    context = load_search_context(settings, embed_model=embedding)
    requests = []

    def respond(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            return httpx.Response(200, json=tool_response("RotorQ"))
        assert DESCRIPTION not in json.dumps(body, ensure_ascii=False)
        content = [
            item
            for message in body["input"]
            if isinstance(message.get("content"), list)
            for item in message["content"]
        ]
        images = [item for item in content if item["type"] == "input_image"]
        assert len(images) == 1
        assert images[0]["detail"] == "high"
        with Image.open(
            io.BytesIO(base64.b64decode(images[0]["image_url"].split(",", 1)[1]))
        ) as image:
            assert image.format == "JPEG"
        output = next(item for item in body["input"] if item.get("type") == "function_call_output")
        matches = json.loads(output["output"])["matches"]
        return httpx.Response(
            200,
            json=response_payload(
                {
                    "answer": "المحرك موضح باللون الأحمر [1].",
                    "cited_chunk_ids": [matches[0]["chunk_id"]],
                }
            ),
        )

    async def run():
        async with api_client(respond) as client:
            return await ask_agent(
                "ما لون المحرك؟", context=context, client=client, settings=settings
            )

    answer = asyncio.run(run())
    assert answer["sources"][0]["metadata"]["images"]
    assert DESCRIPTION not in json.dumps(
        load_session(answer["session_id"], settings=settings), ensure_ascii=False
    )


def test_new_uploads_opt_in_while_existing_records_keep_old_processing(tmp_path):
    settings = web_settings(tmp_path)
    registry = Registry(settings.web_data_dir)
    resource = pdf_resource()
    old_id = str(uuid4())
    original = f"{old_id}.pdf"
    (registry.uploads / original).write_bytes(resource["data"])
    registry.add("old.pdf", len(resource["data"]), file_id=old_id, original=original)
    seen = []

    async def prepare(resource, settings, progress):
        seen.append((resource["file_name"], resource["include_images"]))
        return page_nodes(resource)

    with TestClient(
        create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        new = client.post("/api/files", files={"file": ("new.pdf", resource["data"])}).json()
        for file_id in [old_id, new["id"]]:
            client.post(f"/api/files/{file_id}/train")
            wait_status(client, file_id, "trained")
    assert seen == [("old.pdf", False), ("new.pdf", True)]


@pytest.mark.parametrize("operation", ["unindex", "delete"])
def test_visual_sources_survive_restart_and_are_removed_with_indexing(tmp_path, operation):
    settings = web_settings(tmp_path)
    resource = pdf_resource()

    async def prepare(resource, settings, progress):
        return await enrich(resource, settings)

    embedding = MockEmbedding(embed_dim=2)
    with TestClient(create_app(settings, prepare=prepare, embed_model=embedding)) as client:
        row = client.post(
            "/api/files", files={"file": (resource["file_name"], resource["data"])}
        ).json()
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "trained")
        nodes, _ = read_index_nodes(settings)
        chunk_id = next(
            node.node_id for node in nodes if node.metadata.get("node_kind") == "image_description"
        )
    with TestClient(create_app(settings, prepare=prepare, embed_model=embedding)) as client:
        detail = client.get(f"/api/sources/{chunk_id}").json()
        assert DESCRIPTION not in json.dumps(detail, ensure_ascii=False)
        assert detail["images"][0]["kind"] == "figure"
        url = detail["images"][0]["url"]
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert client.get(f"/api/sources/{chunk_id}/images/{uuid4()}").status_code == 404
        if operation == "delete":
            client.delete(f"/api/files/{row['id']}")
        else:
            client.post(f"/api/files/{row['id']}/unindex")
            assert client.get(f"/api/files/{row['id']}/download").content == resource["data"]
        assert client.get(url).status_code == 404
        assert client.get(f"/api/sources/{chunk_id}").json()["available"] is False
        assert not list((settings.web_data_dir / "images").glob("*.jpg"))


def test_warning_is_visible_in_library_and_embedding_failure_cleans_images(tmp_path):
    settings = web_settings(tmp_path)
    resource = pdf_resource()

    async def prepare(resource, settings, progress):
        return await enrich(resource, settings, fail=True)

    class BrokenEmbedding(MockEmbedding):
        def get_text_embedding_batch(self, texts, **kwargs):
            raise ValueError("Embedding failed")

    with TestClient(
        create_app(settings, prepare=prepare, embed_model=BrokenEmbedding(embed_dim=2))
    ) as client:
        row = client.post("/api/files", files={"file": ("new.pdf", resource["data"])}).json()
        client.post(f"/api/files/{row['id']}/train")
        wait_status(client, row["id"], "failed")
    assert not list((settings.web_data_dir / "images").glob("*.jpg"))
    with TestClient(
        create_app(settings, prepare=prepare, embed_model=MockEmbedding(embed_dim=2))
    ) as client:
        client.post(f"/api/files/{row['id']}/train")
        assert wait_status(client, row["id"], "trained")["warning"]


def test_real_prepare_pipeline_calls_visual_enrichment_only_when_opted_in(tmp_path, monkeypatch):
    from advanced_rag import visuals
    from advanced_rag.ingestion import documents

    async def extractor(resource):
        return page_nodes(resource)

    async def split(pages, *, settings):
        return [node.model_copy(deep=True) for nodes in pages.values() for node in nodes]

    monkeypatch.setattr(documents, "get_pdf_extractor", lambda settings, progress: extractor)
    monkeypatch.setattr(documents, "create_chunks", split)
    monkeypatch.setattr(visuals, "AsyncOpenAI", lambda **kwargs: api_client(caption_response))
    settings = web_settings(tmp_path).model_copy(update={"openai_api_key": SecretStr("test-key")})
    resource = pdf_resource()
    stages = []
    nodes = asyncio.run(prepare_document(resource, settings, stages.append))
    assert stages == ["extracting", "chunking", "describing_images"]
    assert any(node.metadata.get("node_kind") == "image_description" for node in nodes)
    resource["include_images"] = False
    nodes = asyncio.run(prepare_document(resource, settings, lambda stage: None))
    assert all("images" not in node.metadata for node in nodes)


def test_image_addresses_cannot_escape_store_and_startup_prunes_orphans(tmp_path):
    settings = web_settings(tmp_path)
    with pytest.raises(ValueError):
        image_path(settings, "../../secrets")
    orphan = image_path(settings, str(uuid4()))
    orphan.parent.mkdir(parents=True)
    orphan.write_bytes(b"orphan")
    foreign = orphan.parent / "foreign.jpg"
    foreign.write_bytes(b"foreign")
    with TestClient(create_app(settings)):
        assert not orphan.exists()
        assert foreign.exists()
