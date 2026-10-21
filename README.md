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
    B -- Word / TXT --> W["Use filename as section metadata"]
    M --> S["SentenceSplitter: 1024 tokens / 50 overlap"]
    W --> S
    S --> D["Embeddings + FAISS + BM25"]
    S -- PDF visuals enabled --> V["Extract PDF images + describe them for search"]
    V --> D
```

PDF chunks inherit page and section metadata; headings do not define chunk boundaries.
If no PDF sections are found, the filename is used as the section fallback.

## Retrieval process

```mermaid
flowchart TD
    D["Indexed chunks + image descriptions"]
    Q["Your question"] --> Dense
    Q --> Lexical
    D --> Dense
    D --> Lexical
    subgraph Candidates["Stage 1: candidate retrieval"]
        Dense["FAISS semantic search: up to 20 hits"] --> F["RRF fusion: keep up to 20 candidates"]
        Lexical["BM25 keyword search: up to 20 hits"] --> F
    end
    subgraph Reranking["Stage 2: relevance reranking"]
        G["BGE cross-encoder: rerank candidates → top 5"]
    end
    F --> G
    G --> H["Original text + related images → answer with sources"]
```

Retrieval first finds candidates, then reranks them.
The 20-candidate and top-5 limits are configurable defaults.

<details>
<summary>More screenshots</summary>

![Independent assistant workspaces](docs/images/assistants.png)

![Upload and index documents in the library](docs/images/library.png)

![Inspect the source behind an answer](docs/images/source.png)

</details>

*Real app UI with illustrative data and a preset answer. “Train” indexes your documents.*

[Get the app](https://github.com/HUSSAMX7/Advanced_RAG/tree/main) · [Setup & usage guide](docs/usage.md)
