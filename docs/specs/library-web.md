# Local library and chat

Baseline: `9143356`. Build on the existing ingestion and chat functions.

- Arabic RTL React/TypeScript interface; opens on chat. Sidebar has Library,
  New conversation, then saved conversations. One local library, no accounts.
- Upload PDF, DOCX, DOC and UTF-8 TXT, up to 50 MiB per file. Uploading does not
  index the document. DOC uses headless LibreOffice conversion to DOCX.
- Each file has persisted status and extraction/chunking/storage stages. Index
  success is shown only after durable vector storage. One writer at a time.
- Cancel queued/running training; discard unpublished chunks. Remove indexing
  of a trained file while retaining its upload; deletion removes both its upload
  and indexed chunks. Failed/cancelled work can be retried without duplicates.
- Chat works immediately without uploaded or trained files for general questions.
  The agent chooses whether to answer directly or search all currently indexed
  library files when the question needs their contents. Direct answers have no
  document sources. Preserve source validation for searched answers and saved
  conversation history for both modes. Show source names,
  page numbers where applicable, and supporting excerpts when available.
- Refresh retrieval after every corpus change. Preserve past conversations
  when a source is deleted, marking its source as unavailable.
- Rerank retrieved excerpts locally with BAAI/bge-reranker-v2-m3 on CPU.
  Cache the model, serialize inference off the event loop, preserve source metadata,
  and fail clearly on unavailable models or invalid scores. General chat skips reranking.
- Persist uploads/statuses in SQLite and retain existing JSON chat sessions.
  Use staged index generations with atomic publication and startup recovery.
- Existing PDF CLI and retrieval CLI stay compatible with persisted indexes.
- Verify upload/training/cancel/unindex/delete and chat/session behavior through
  the HTTP interface and persistence through the public storage functions.
  Use real FAISS with fake embedding/extraction/model providers in tests.
