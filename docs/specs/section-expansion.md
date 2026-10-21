# Section expansion after chunk retrieval

The requested behavior follows the supplied `section_retrieve` reference:
use relevant chunks as pointers, then load their surrounding subsection or
section from the same file before generating an answer.

This extends the historical [retrieval specification](retrieval-agent.md).
The current retrieval path uses local BGE reranking and FAISS storage.

## Retrieval contract

1. Search indexed chunks and image descriptions with FAISS and BM25.
2. Fuse the rankings with RRF, rerank the candidate pool with BGE, and select
   up to `RETRIEVAL_TOP_K` seed chunks (default 5).
3. For each seed, find indexed nodes belonging to the same file and main
   `section_id`. Prefer its `sub_section_id` when it is nonempty and distinct
   from the main section. If no matching subsection is available, use the main
   section. This loads existing nodes; it does not issue another embedding or
   model request.
4. Deduplicate by original chunk ID. Keep documents in the order of their first
   selected seed, then order passages within each document by page number and
   persisted chunk order. Missing page numbers sort as page 0. If no seed
   expands beyond itself, preserve the original seed ranking.
5. Return original evidence and metadata through the existing `SearchHit`
   interface. Each passage retains its own chunk ID, page, and source preview.
   Generated image descriptions remain retrieval aids: return their associated
   original text and images as evidence, with private metadata removed.

## File identity and fallbacks

- Uploaded documents use their `resource_id`, so matching names and section
  labels in different uploads cannot mix their context.
- Legacy documents without a resource ID use the storage layer's existing
  source/path identity. Legacy uploads with identical names and no distinct
  resource IDs cannot be distinguished by name alone.
- Missing file identity or section metadata keeps the original seed rather
  than expanding into unrelated nodes.
- The generated `0: filename` section is an ordinary section for this purpose:
  it can expand to the entire indexed file. This covers Word, TXT, and PDFs
  without detected sections.
- Expansion uses only the currently loaded assistant index. Unindexed or
  deleted documents do not supply expansion nodes after index refresh.

## Scope and limits

No storage migration, new dependency, API response schema, model, or reindexing
is required. Existing section metadata is reused. Sections are page annotations;
they are not exact heading boundaries within a page.

`RETRIEVAL_TOP_K` now limits seeds, not final passages. Large sections or
filename-fallback documents can substantially increase prompt size. Expanded
evidence is not silently truncated or summarized; the existing conversation
compaction and explicit context-capacity error still apply. Actual answer
quality must be evaluated on representative documents.

## Verification

Regression tests use real temporary FAISS indexes and mock model responses.
They cover expansion beyond the initial candidate pool, subsection preference,
main-section expansion, same-name file isolation, legacy identity, missing
metadata, overlapping seed deduplication, page/chunk ordering, whole-file
fallback, original visual evidence, and a cited expanded passage that remains
available through the web source endpoint.

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src/advanced_rag/agent src/advanced_rag/retrieval src/advanced_rag/config.py tests
uvx ty check src/advanced_rag/retrieval src/advanced_rag/config.py
```
