# Setup & usage guide — Advanced RAG

This guide covers the Madar web app, CLI tools, document extraction, retrieval,
and storage. The app supports PDF, Word, and TXT, with local FAISS indexing.

```text
PDF → LlamaParse / LightOnOCR → LLM section extraction and review
    → Map sections to pages → SentenceSplitter (1024 / overlap 50) → FAISS
```

The current application is on `main`. See the [project README](../README.md)
for screenshots and a brief introduction.

## Requirements and installation

Install Python 3.13+, uv, and Node.js 20.19+ or 22.12+ for the frontend build.

```powershell
git clone https://github.com/HUSSAMX7/Advanced_RAG.git
cd Advanced_RAG
uv sync
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
npm --prefix frontend ci
npm --prefix frontend run build
uv run advanced-rag-web
```

Open [http://127.0.0.1:8001](http://127.0.0.1:8001).
For frontend development, keep the backend running and run
`npm --prefix frontend run dev` in a second terminal. Vite proxies `/api`
requests to the local backend.

## Web app

### Assistants and sign-in

The React and TypeScript interface is in Arabic. It opens on the assistant
cards. Create an assistant with a name and optional description and answer
instructions, then open its card to access its chat and library. Each assistant
has its own files, index, extracted images, and conversations. You can edit an
assistant or delete it and its data after confirmation.

Email sign-in through Supabase Auth is optional. Each account or guest session
has separate data, settings, and API keys. Guests have access to all features.
A renewal prompt appears every 15 minutes with a one-minute grace period.
Guest data is deleted when the session ends or expires. Refreshing preserves
the session; closing and reopening starts a new one. Server cleanup uses a
close notification with an expiration fallback. Signing in does not transfer
guest work to the account.

See [email sign-in setup](setup-email-signin.md) and
[accounts and guest sessions](specs/identity-and-guest-sessions.md).

### Settings and API keys

In **Settings**, enter your OpenAI key, choose your models, and select a PDF
extraction provider. LlamaParse also requires its own API key.

Keys are encrypted at rest and are not returned to the browser.
`WEB_CREDENTIAL_ENCRYPTION_KEY` provides portable encryption for servers;
without it, the app uses local Windows protection. Web settings take precedence
over `.env` and apply after saving without a restart. `.env` remains the source
of initial configuration and CLI settings.

Settings cannot be saved while that user has training or an answer in progress.
The embedding model cannot change while any of the user's assistants has
indexed files: remove their indexes, change the model, then index them again.
CLI keys from `.env` are not copied into web accounts or guest sessions; each
user supplies their own keys.

### Upload, train, and ask

Supported formats are **PDF, DOCX, DOC, and UTF-8 TXT**.

- Uploading only saves the file. Click **Train** to extract content, split it,
  create embeddings, and publish its index. This is indexing, not model training.
- **Trained** appears only after the completed index becomes active. The library
  shows extraction, chunking, and storage progress. Queued files run sequentially.
- **Stop** cancels queued or active training. An embedding request already in
  progress finishes, but its result is discarded without being published.
- **Remove indexing** removes a file's chunks from search and keeps the original.
  **Delete file** removes both. Previous conversations remain saved.
- Answer sources show the file name, page when available, and supporting passage.
  Opening an old citation after its source is removed shows it as unavailable.
- Files previously indexed through the CLI appear in the library. Downloading
  or retraining them requires uploading the original if it is not already saved.

The assistant is prompted to treat short, substantive questions as potentially
related to its files and search when their contents may be relevant, even
without an explicit search request. Greetings and clearly general questions
remain available without files. Tool selection is automatic, so this prompting
does not force a search for every message.

DOCX extraction preserves paragraph and table order; it does not extract text
from embedded images. Legacy DOC files require
[LibreOffice](https://www.libreoffice.org/download/download-libreoffice/) for
automatic conversion to DOCX in headless mode. The app checks common Windows
installation paths, or you can set `LIBREOFFICE_PATH`. Conversion has a two-minute
timeout. Other formats do not require LibreOffice.

### Local LightOnOCR

Selecting local LightOnOCR starts the model automatically when you train a PDF.
No separate OCR server, URL, or OCR key is required. The first run downloads
`lightonai/LightOnOCR-2-1B` (approximately 2 GB); later runs use the cache.

OCR runs on CPU in a separate process, one page at a time. The process exits
after extraction or cancellation, and BGE is released from memory before OCR
starts. Failed pages or truncated text fail training rather than saving an
incomplete document. There is no automatic cloud fallback.

Chat, PDF section detection, and embeddings still use OpenAI. CPU extraction
can be slow, and Arabic support is limited according to the
[developers' paper](https://arxiv.org/html/2601.14251v1).

### PDF images and diagrams

Newly uploaded PDFs support images and diagrams; older files retain their
existing processing behavior. During training, images are extracted and given
Arabic and English descriptions for retrieval. These descriptions are used by
FAISS, BM25, and reranking. The answer model receives the original text and
associated images. Source previews show images with a zoom option. If the
relationship between a figure and its text is unclear, the full original page
image is attached instead.

Image descriptions and answers use `AGENT_MODEL` and the saved OpenAI key.
Choose a vision-capable model even when using local OCR. Images are stored
under the library's local `images/` directory (`storage/library/images/` in
legacy local mode). Removing indexing or deleting a file removes its indexed
image assets. Some image failures do not prevent successful text and images
from being saved; the library displays a warning.

See [multimodal RAG](specs/multimodal-rag.md) for behavior and limitations.

## Storage and runtime behavior

`WEB_DATA_DIR` defaults to `storage/library`. Each account or guest has a
workspace under `owners/accounts/<id>/` or `owners/guests/<id>/` containing its
records, settings, and assistants. Each assistant's directory contains
`library/`, `index/`, and `conversations/`.

When `RAG_SUPABASE_URL` and `RAG_SUPABASE_SECRET_KEY` are configured, original
uploads use private Supabase Storage. Configure the bucket once:

```powershell
uv run python scripts/configure_storage.py
```

Local originals then act as a processing and download cache and can be restored
from Supabase if missing. Assistant records, file metadata, conversations,
settings, indexes, and extracted images remain local. See
[Supabase file storage](specs/supabase-storage.md).

Set `WEB_IDENTITY_ENABLED=false` explicitly to use the legacy local workspace
and its original assistant registry and settings. The web API uses
`/api/assistants/<id>/files`, `/sessions`, and `/sources`. Legacy API routes and
CLI directories remain separate for compatibility.

`RAG_MAX_UPLOAD_BYTES` (also accepted as `MAX_UPLOAD_BYTES`) defaults to 50 MiB
per file; `.env.example` sets it to 20 MiB. OpenAI and extraction keys stay on
the server. Word and TXT need OpenAI for embeddings and chat; PDF also needs
an extraction provider.

Run the server with one worker. An application lock prevents two servers from
using the same data. Training and retrieval operations involving local models
are serialized across assistants.

Indexes are written as staged generations and activated with an atomic pointer.
Cancellation before activation preserves the previous index. Retrying a file
does not duplicate its chunks. Removing chunks rebuilds the index from remaining
vectors without recomputing embeddings. Retrieval refreshes when the index
changes, and incomplete file operations are reconciled at server startup.

## CLI: ingest PDFs

Set `OPENAI_API_KEY` for section detection and embeddings, then configure the
extraction provider in `.env`:

- `llamaparse`: set `LLAMA_PARSE_API_KEY`.
- `lightonocr`: set `LIGHTONOCR_LOCAL=true` for direct local execution, or set
  `LIGHTONOCR_URL` and `LIGHTONOCR_LOCAL=false` for a separate OCR server.

`LIGHTONOCR_URL` may point to a local server, such as
`http://localhost:8000/v1/chat/completions`. Server mode connects to a separately
running LightOnOCR service with an OpenAI-compatible API, such as vLLM.
Setting the URL does not start that server. This mode applies to PDF extraction
when `PDF_PROVIDER=lightonocr` or `--provider lightonocr` is selected. The web
app's local OCR option uses direct execution and ignores this URL.

```powershell
uv run main.py "D:/documents/report.pdf"
uv run main.py "D:/documents/report.pdf" --provider lightonocr
```

You can pass multiple files. The CLI saves chunks locally and prints a JSON
result for each file: `file_id`, `file_name`, `success`, and `error`. Other options
include `--persist-dir` and `--assistant-id`.

The default index directory is `storage/pdf_documents`, configurable through
`FAISS_PERSIST_DIR` or `--persist-dir`. The saved index includes text, metadata,
and vector mappings. Subsequent runs load it and add new chunks. Use the same
embedding model for ingestion and retrieval; changing it requires a new
directory and reindexing.

```python
from dotenv import load_dotenv
from advanced_rag import Settings
from advanced_rag.storage import load_faiss_index

load_dotenv()
index = load_faiss_index(Settings())
results = index.as_retriever(similarity_top_k=5).retrieve("A question about the document")
```

`IndexFlatL2` performs exact search over all vectors. Search time and memory
usage grow with the number of chunks. Scores are squared L2 distances; lower
is closer. The FAISS integration does not directly support metadata filtering
or document deletion; the library rebuilds the index from remaining vectors
when removing a file. A directory lock allows only one writer at a time.

## CLI: chat with the agent

After ingesting PDFs, set `OPENAI_API_KEY` and run:

```powershell
uv run advanced-rag-chat
uv run advanced-rag-chat --question "What is the amount of invoice ZX-774?"
uv run advanced-rag-chat --session "your-saved-session-uuid"
uv run advanced-rag-chat --persist-dir storage/pdf_documents --sessions-dir chat_sessions
```

Type `/exit` to leave. Results include the answer, file and page references,
and session UUID. `--session` requires an existing saved session; an invalid
ID does not silently create a replacement. Run only one chat process per session.

Questions, answers, and sources are stored locally in `chat_sessions/`. Each
question includes the conversation history in order, distinguishing user
messages from model responses. If the request exceeds the model's context
capacity, older turns are summarized automatically with the selected chat model,
while retaining the latest 10 complete exchanges. All original messages remain
saved and visible. The summary is conversation context, not document evidence.

Summarization adds model requests as needed. If the recent messages, question,
and search results still exceed capacity, the request fails with a clear error.
Failed questions and memory changes from failed requests are not saved.

### Retrieval and model settings

The model answers general questions directly. When needed, `search_documents`
searches the index once for a document-related question. It collects up to 20
semantic and 20 keyword results, merges them with RRF, reranks the best 20
locally with BGE, and selects the top 5 seed chunks. Each seed then expands to
all indexed passages in its subsection, or its main section when there is no
distinct subsection. Expansion stays within the same file, deduplicates chunk
IDs, and orders passages by page and stored chunk order. Files follow their
first seed's relevance rank. The agent uses the OpenAI SDK directly, without
LangChain or the Agents SDK.

The final context can contain more than 5 passages. Missing section or file
metadata keeps the original seed. Files assigned the filename-based fallback
section can expand to the whole file. Existing indexes work without retraining;
the original chunk IDs, text, images, and citation metadata are preserved.
Large sections are passed in full and may exceed the model's context capacity;
the existing context error is returned rather than silently truncating evidence.
See [section expansion](specs/section-expansion.md).

One search is not one OpenAI request: tool-query generation, question embeddings,
and answer generation can require separate requests. Reranking runs locally.

`AGENT_MODEL` defaults to `gpt-6-luna`. `RERANK_MODEL` defaults to
[`BAAI/bge-reranker-v2-m3`](https://huggingface.co/BAAI/bge-reranker-v2-m3).
BGE runs on CPU through `sentence-transformers`, loads on first search, and
stays in memory. The first download needs internet access; later runs use the
Hugging Face cache. `RERANK_MODEL` can also be a local model directory.
The configured PyTorch distribution is CPU-only.

`RERANK_BATCH_SIZE` defaults to 1 to reduce memory use. `RERANK_MAX_LENGTH`
defaults to 2048 tokens per question/passage pair. Longer pairs are truncated
for relevance scoring; original passages remain intact for answer generation.
CPU reranking may be slow. It runs outside the server event loop and is
serialized to avoid loading multiple copies of the model.

Adjust candidate and seed counts with `RETRIEVAL_CANDIDATES` and
`RETRIEVAL_TOP_K`; the latter does not cap expanded passages. Arabic and English
normalization applies only to keyword
search; original text, numbers, and dates are preserved. CLI chat builds BM25
when it starts, so restart it after adding documents.

For Python usage:

```python
import asyncio
from dotenv import load_dotenv
from openai import AsyncOpenAI
from advanced_rag import Settings
from advanced_rag.agent import ask_agent
from advanced_rag.config import require_openai_key
from advanced_rag.retrieval import load_search_context

async def main():
    load_dotenv()
    settings = Settings()
    context = load_search_context(settings)
    async with AsyncOpenAI(api_key=require_openai_key(settings)) as client:
        result = await ask_agent("What are the invoice details?", context=context,
                                 client=client, settings=settings)
        print(result["answer"], result["sources"], result["session_id"])
        # Pass session_id=result["session_id"] to continue the conversation.

asyncio.run(main())
```

Invalid reranking output or API failures produce explicit errors rather than
silently returning unranked results. Source IDs and citation numbers are
validated before saving the answer. The agent is instructed to acknowledge
insufficient evidence; answer quality still needs evaluation on your documents.

### Conversation titles

The web app generates a title from the first message in an independent OpenAI
task alongside the answer. The sidebar and conversation header show a loading
indicator until the title is ready. Answer generation does not wait for it.
Title state is persisted, and pending tasks resume after server restart.

`TITLE_MODEL` defaults to `gpt-6-luna` and can be changed in Settings. A failed
title shows an error state and a retry button without duplicating the message
or blocking the answer. Follow-up messages do not regenerate the title.

## Extraction details

PDF text goes through these steps before indexing:

1. The selected chat model extracts numbered section headings from each page,
   including the title, starting page, and subsection flag. The prompt requires
   headings to begin with `#` and contain a section number; figures and tables
   do not count as sections.
2. A separate LLM call reviews the collected sections and selects valid entries.
3. Each page is annotated with `section_id` and `sub_section_id` according to
   section starting pages. If no valid sections remain, both fields use
   `0: file name`.
4. `SentenceSplitter(chunk_size=1024, chunk_overlap=50)` splits the annotated
   page nodes into chunks, preserving their metadata. Empty chunks are removed.

Section detection adds context to the chunks; it does not split the document
at heading boundaries. Word and TXT skip LLM section extraction, use the filename
as section metadata, and apply the same sentence splitter. Image-only PDFs can
skip text chunking and continue through visual enrichment when enabled.

Section extraction and review use the selected chat model and OpenAI key.

LightOnOCR's `postprocess` cleans repetitions, selected Arabic words, and HTML
tables, and skips blank pages. Disable it with `LIGHTONOCR_POSTPROCESS=false`.
A page extraction failure stops training for the file.

The original LlamaParse `tier` and `version` settings are retained, but pinned
SDK version `0.6.54` warns that it ignores them.

## Code organization

```text
src/advanced_rag/
├── ingestion/                # Document extraction and chunk preparation
│   ├── providers/
│   │   ├── llamaparse.py     # Page extraction through LlamaParse
│   │   └── lightonocr.py     # LightOnOCR extraction and postprocessing
│   ├── sections.py          # Section extraction, review, and page mapping
│   ├── chunking.py          # Sections followed by SentenceSplitter
│   └── pipeline.py          # Extract, prepare chunks, and store
├── retrieval/                # FAISS + BM25 + RRF and local BGE reranking
├── agent/                    # OpenAI agent, CLI chat, and session storage
├── web/                      # FastAPI organized by feature
│   ├── app.py                # App creation, routers, and lifecycle
│   ├── identity/             # Accounts, guest sessions, and data isolation
│   ├── assistants/           # Assistants and their libraries
│   ├── files/                # Upload, download, training, and sources
│   ├── conversations/        # Conversations, answers, and titles
│   └── settings/             # User settings and encrypted credentials
├── storage.py                # Embeddings and FAISS persistence
├── models.py                 # File metadata and processing results
├── config.py                 # Runtime configuration
└── cli.py                    # Pipeline entry point
```

`process_pdfs` coordinates processing and file results. `create_chunks` extracts
sections, maps them to pages, and splits content without storing it.
`storage.py` manages the persisted index. Tests follow the same boundaries.

Web features group `routes.py`, `schemas.py`, `services.py`, and `repository.py`
where those responsibilities exist. Operations and persistence use functions
with explicit dependencies. Classes serve concrete needs such as validation
contracts or lock and task state. See [backend architecture](architecture.md).

## Local checks

```powershell
uv run pytest -q
uv run ruff check src/advanced_rag/agent src/advanced_rag/retrieval tests
uvx ty check src/advanced_rag/agent src/advanced_rag/retrieval src/advanced_rag/config.py
```

Tests use mocked provider responses and real FAISS indexes in temporary
directories. They do not call live extraction services or OpenAI.
