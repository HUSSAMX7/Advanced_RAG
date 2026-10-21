<div align="center">

# Madar | Advanced RAG

### Upload a file. Ask questions. No manual preprocessing.

The goal: demonstrate high-quality RAG retrieval and answers without manually cleaning, restructuring, or splitting your files beforehand.

**Upload → Train → Ask.** Madar handles document processing automatically.

</div>

![Madar answering a document question with a source citation](docs/images/chat.png)

**PDF · Word · TXT** | Hybrid search + reranking | PDF images & diagrams | Answers with sources

## How it works

```mermaid
flowchart TD
    A["Upload PDF / Word / TXT"] --> B["Extract content"]
    B --> C["Detect PDF sections + split text into chunks"]
    C --> D["Embeddings + FAISS + BM25"]
    B --> V["Extract PDF images + describe them for search"]
    V --> D
    Q["Your question"] --> E["Hybrid retrieval"]
    D --> E
    E --> F["Merge rankings with RRF"]
    F --> G["BGE reranking → top 5 passages"]
    G --> H["Original text + related images → answer with sources"]
```

<details>
<summary>More screenshots</summary>

![Independent assistant workspaces](docs/images/assistants.png)

![Upload and index documents in the library](docs/images/library.png)

![Inspect the source behind an answer](docs/images/source.png)

</details>

*Real app UI with illustrative data and a preset answer. “Train” indexes your documents.*

[Get the app](https://github.com/HUSSAMX7/Advanced_RAG/tree/main) · [Setup & usage guide](docs/usage.md)
