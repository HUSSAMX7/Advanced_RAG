# Web settings and automatic local OCR

## Confirmed requirements

- The Arabic React web application has a Settings page for managing its
  configuration rather than requiring users to edit environment files.
- The user can choose local LightOnOCR or an API-based PDF extraction provider
  and enter the provider's API key through the web interface.
- LightOnOCR must be able to run on the user's own computer.
- Preserve the existing local library, trained files, and saved conversations.
- Local OCR is PDF text extraction; training remains extraction, chunking,
  embedding, and indexing, without changing model weights.
- Settings scope is extraction provider, API keys, and model choices only.
  Do not add advanced retrieval, upload-limit, or performance controls.
- Local LightOnOCR starts automatically when a PDF is trained with that
  provider selected. A stopped service is not a reason to send files elsewhere.
- Failed local extraction stops training and displays its cause; do not
  automatically switch to a cloud provider.

## Implementation decisions

- PDF provider choices are local LightOnOCR and the existing LlamaParse API.
- Keep BGE as the default local reranker; expose its model ID, the local OCR
  model ID, the OpenAI chat model, and the OpenAI embedding model.
- Persist keys with user-scoped Windows DPAPI. The API returns configured
  flags, never stored key values. Empty inputs retain existing keys; an explicit
  remove action clears a key only when the user saves.
- Apply saved settings without restarting the web server. Reject saves while
  training, corpus mutation, or an answer is active to preserve a consistent
  configuration for each operation. Invalidate cached embedding clients on save.
- Reject embedding-model changes while any indexed documents exist. Retain
  original uploads so users can remove indexing, change the model, and retrain.
- Preserve `.env` as the initial configuration and CLI compatibility; persisted
  web settings override it for the web application.
- Local OCR does not require an HTTP server or URL. Start its worker at PDF
  training, extract pages sequentially, terminate on cancellation, and release
  the process after extraction. Release cached BGE before OCR starts.
- Show preparation and page extraction progress. Any failed page or truncated
  generation fails the job; never mark incomplete training successful.
- PDF section identification uses the saved OpenAI key and chat model through
  Responses, preserving support for model IDs unknown to LlamaIndex's catalog.

## Verified facts and implementation implications

- Current configuration is loaded from environment variables and `.env`.
- The existing LightOnOCR provider calls a separate HTTP service.
- The user's Windows computer has approximately 8 GB RAM and Intel UHD
  graphics, with no NVIDIA device reported. The official model example has
  a CPU execution branch using Transformers v5; performance on this computer
  still requires a real page extraction test.
- Settings are held by the web application and library for their lifetime;
  the current implementation cannot apply changed values through the UI.
- PDF section extraction currently constructs a fixed OpenAI model without
  using the application's Settings. Web-managed credentials and model choices
  must also reach this stage of training.
- The current HTTP OCR path logs and drops failed pages. Local OCR must not
  silently publish incomplete extraction as successful training.
- The OCR provider's default concurrency of 64 was designed for an external
  service. CPU execution on this computer needs a much smaller concurrency.
- The model authors state that Arabic and other non-Latin scripts are not
  fully supported. Local Arabic OCR quality needs explicit verification.
- Official LightOnOCR weights are approximately 2.01 GB. There is currently
  very little free physical memory on this computer; do not keep OCR and BGE
  resident simultaneously. Prefer sequential local model work and release the
  OCR worker after extraction completes or is cancelled. This is a resource
  management recommendation, not a measured performance guarantee.
- Existing indexed metadata does not record embedding-model identity;
  accepting a different model with the same dimensions can still corrupt
  relevance. Any settings design must prevent mixing embedding models.

Sources: [official model card](https://huggingface.co/lightonai/LightOnOCR-2-1B),
[authors' paper, limitations](https://arxiv.org/html/2601.14251v1).
Model size: [official weights](https://huggingface.co/lightonai/LightOnOCR-2-1B/blob/main/model.safetensors).

The user confirmed the scope, automatic OCR startup, and explicit failure
behavior, then requested implementation. Remaining routine choices follow the
recommendations recorded above.
