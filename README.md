<div align="center">

# Madar | Advanced RAG

### Your documents, as they are. Answers, with sources.

**PDF · Word · TXT · Hybrid Search · Multimodal RAG · Arabic UI**

[Get started](#quick-start) · [App screenshots](#inside-the-app) · [Application code](https://github.com/HUSSAMX7/Advanced_RAG/tree/develop)

</div>

![Madar: a document question answered with a source citation](docs/images/chat.png)

## Project goal

**Show how strong RAG retrieval and answers can be without manually preparing documents beforehand.** Upload your files as they are—no manual text extraction, cleanup, restructuring, or splitting before upload.

Madar handles extraction, chunking, embeddings, and indexing automatically after you click **Train**. Ask a question, then open the cited source to inspect the supporting passage.

**Create an assistant → Upload files → Train → Ask.**

## What powers the answers?

- **Hybrid retrieval:** FAISS semantic search + BM25 keyword search, merged with RRF and reranked locally with BGE.
- **Text and visuals:** PDF images and diagrams can be retrieved alongside text and passed to a vision-capable answer model.
- **Traceable sources:** inspect the file, page when available, and passage behind an answer.
- **Separate knowledge spaces:** each assistant has its own files, index, instructions, and conversations.

## Inside the app

<details>
<summary>View assistants, the document library, and source previews</summary>

**Assistants — a separate workspace for each topic.**

![Independent assistant workspaces](docs/images/assistants.png)

**Library — upload supported files and click Train to prepare them for search.**

![Document library with indexed files and a file awaiting training](docs/images/library.png)

**Sources — open the passage used in an answer.**

![Source preview with a passage and page reference](docs/images/source.png)

</details>

*Screenshots show the real UI with illustrative sample data and a preset answer.*

## Quick start

The application is on **[`develop`](https://github.com/HUSSAMX7/Advanced_RAG/tree/develop)**. Requires Python 3.13+, uv, and Node.js 20.19+ or 22.12+.

```powershell
git clone --branch develop https://github.com/HUSSAMX7/Advanced_RAG.git
cd Advanced_RAG
uv sync
Copy-Item .env.example .env
npm --prefix frontend ci
npm --prefix frontend run build
uv run advanced-rag-web
```

Open [localhost:8001](http://127.0.0.1:8001), continue as a guest, and add your OpenAI key in **Settings**. For PDF extraction, choose LlamaParse with its key or local LightOnOCR. Create an assistant, upload files, and click **Train** before chatting.

Supported: **PDF, DOCX, DOC, and UTF-8 TXT**. Legacy DOC requires LibreOffice. “Train” means document indexing; local OCR still uses OpenAI for embeddings and answers.

[Detailed setup & CLI guide (Arabic)](docs/usage.md) · [Architecture](https://github.com/HUSSAMX7/Advanced_RAG/blob/develop/docs/architecture.md)
