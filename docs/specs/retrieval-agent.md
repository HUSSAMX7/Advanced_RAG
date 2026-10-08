# Hybrid retrieval and OpenAI chat

Approved in the chat before implementation. Review baseline:
`3e726ad7584317dce3c41ccb4954610c1deebef0`.

- Preserve PDF extraction, section annotation, chunking, and existing FAISS storage.
- Framework restriction applies to the agent only. Existing LlamaIndex retrieval is allowed.
- Use functions and dictionary interfaces; no LangChain or Agents SDK in the agent.
- Load the existing FAISS index and build BM25 once per interactive session over indexed chunks.
- Search all documents, with no assistant or resource filters. Retrieve up to 20 dense and 20
  lexical candidates, fuse by RRF with k=60, deduplicate by chunk ID, rerank the top 20 through
  OpenAI, and return up to 5 excerpts with unchanged text and metadata.
- Support Arabic and English lexical search; normalize tokens, never stored source values.
- Public interfaces: `load_search_context(settings)`,
  `search_documents(query, *, context, client, settings)`, and
  `ask_agent(question, *, context, client, settings, session_id=None)`.
- Use AsyncOpenAI Responses with one strict `search_documents(query)` tool call per question.
  Disable additional tools for answer generation. Return `answer`, verified `sources`,
  and `session_id`; citations use stored metadata, never model-generated filenames/pages.
- Insufficient evidence must yield a clear non-answer with no citations. Invalid rankings,
  unknown or inconsistent citations, incomplete responses, and API failures are errors,
  without silently bypassing reranking or saving failed turns.
- Persist successful turns locally as JSON, resume by UUID, retain all turns and send only
  the latest 10 exchanges as context. An explicitly missing session is an error.
- Add `advanced-rag-chat` with interactive chat, `--question`, `--session`, `--persist-dir`,
  and `--sessions-dir`. Preserve the existing PDF CLI. No HTTP API or web search.
- Defaults: `gpt-4o-mini` for agent and reranking (separately configurable), `store=False`,
  `chat_sessions/` for local session files excluded from Git, original embedding model.
- Verify through public interfaces using real temporary FAISS indexes and mocked external
  OpenAI HTTP responses. Cover hybrid search, normalization, reranking validation, sources,
  one search per question, session resume/history window, CLI, and failures.
