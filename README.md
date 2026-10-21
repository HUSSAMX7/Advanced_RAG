<div align="center">

# Madar | Advanced RAG

### Upload a file. Ask questions. No manual preprocessing.

The goal: demonstrate high-quality RAG retrieval and answers without manually cleaning, restructuring, or splitting your files beforehand.

**Upload → Train → Ask.** Madar handles document processing automatically.

</div>

![Madar answering a document question with a source citation](docs/images/chat.png)

**PDF · Word · TXT** | Hybrid search + reranking | PDF images & diagrams | Answers with sources

## Chunking process

```mermaid
flowchart TD
    A["Upload PDF / Word / TXT"] --> B["Extract content"]
    B -- PDF text --> C["LLM: extract numbered section headings per page"]
    C --> R["LLM: review and filter sections"]
    R --> M["Map section + subsection metadata to pages"]
    B -- Word / TXT --> S
    M --> S["SentenceSplitter: 1024 tokens / 50 overlap"]
    S --> D["Embeddings + FAISS + BM25"]
    S -- PDF visuals enabled --> V["Extract PDF images + describe them for search"]
    V --> D
```

PDF chunks inherit page and section metadata; headings do not define chunk boundaries.

## Retrieval process

```mermaid
flowchart TD
    Q["Search query"]
    subgraph Candidates["Stage 1: find relevant chunks"]
        Dense["FAISS<br/>Semantic search"] -->|"up to 20"| F["RRF fusion<br/>Top 20 candidates"]
        Lexical["BM25<br/>Keyword search"] -->|"up to 20"| F
        F --> G["BGE reranking<br/>Top 5 seed chunks"]
    end
    subgraph Expansion["Stage 2: expand context"]
        X["Load the matching subsection or section<br/>from the same file"] --> O["Deduplicate + order by page"]
    end
    Q --> Dense
    Q --> Lexical
    G --> X
    O --> Answer["LLM answer<br/>Original text + images<br/>Source citations"]
```

Find relevant chunks first, then expand to their full subsection or section.
The top-5 limit applies to seed chunks; expanded context can contain more passages.
See [section expansion](docs/specs/section-expansion.md) for fallback behavior and limits.

<details>
<summary>More screenshots</summary>

![Independent assistant workspaces](docs/images/assistants.png)

![Upload and index documents in the library](docs/images/library.png)

![Inspect the source behind an answer](docs/images/source.png)

</details>

*Real app UI with illustrative data and a preset answer. “Train” indexes your documents.*

[Get the app](https://github.com/HUSSAMX7/Advanced_RAG/tree/main) · [Setup & usage guide](docs/usage.md)
