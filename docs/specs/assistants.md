# Assistant workspaces

## Confirmed requirements

- Show assistants as cards on an assistants page. Each card displays the
  assistant's name and opens its workspace.
- Build each assistant workspace on the existing Arabic chat and library UI.
- Each assistant has its own uploaded documents. Document search must respect
  that ownership boundary.
- Each assistant owns its saved conversations, their history and source
  references. Direct access to files, images, sources and conversations must
  respect assistant ownership as well as document search.
- "New conversation" opens an unsaved, empty draft and clears any unsent text.
  It creates no saved conversation or sidebar entry until the first message is
  sent. Opening it while another conversation is loading cancels that navigation.
- Creating an assistant requires a name. Description and response instructions
  are optional.
- Provider credentials and model settings remain application-wide. Response
  instructions belong to the individual assistant.
- Keep the existing local application without user accounts.
- The user authorized deleting existing library documents and their indexes
  and all existing conversations instead of migrating them.
- Deleting an assistant permanently deletes its uploads, images, index and
  conversations. Show an explicit confirmation naming those consequences.
- Preserve general chat, but treat substantive and ambiguous questions as
  likely document questions. Prefer calling `search_documents` whenever the
  assistant's files might be relevant, without requiring an explicit request to
  search. Clearly unrelated general requests and greetings can be answered
  directly. Never invent file contents or claim sources without a search.

## Implementation

- Persist assistant names, descriptions and response instructions in a local
  SQLite registry. Give every assistant independent upload, image, FAISS and
  conversation directories; scope all workspace HTTP routes by assistant ID.
- Keep credentials and models in the application's existing settings store.
  Block embedding-model changes while any assistant has indexed documents.
- Serialize local training and retrieval across assistants to preserve the
  current resource limits. Cancel training when deleting its assistant, prevent
  deletion during an active upload/answer, and recover interrupted deletions
  before exposing workspaces after a restart.
- Preserve the original unscoped API and CLI stores for existing integrations;
  they cannot access assistant files or conversations. The web UI uses the
  assistant-scoped routes exclusively.
- The authorized cleanup of this installation's old data is a one-time action,
  not an automatic purge of a user's data on every application startup.

## Validation

- All 119 tests pass with fake model/extraction providers and real FAISS.
  Assistant tests cover independent retrieval/history, cross-assistant file and
  source/image access, persistence, shared settings, deletion during training,
  active-answer conflicts and recovery of interrupted deletion.
- The production React build, Ruff checks for the affected web/agent/config
  modules and tests, and type checks for the affected Python modules pass.
- Browser QA used a disposable local server: created assistant cards, uploaded
  and trained a fixture, sent a question, opened its source and verified the
  scoped original-download URL. A second assistant showed no files or history
  from the first. The saved preview uses these test assistants.
- The existing installation's legacy uploads, images, registry, index and 13
  conversations were removed under the application/index locks with verified
  workspace paths. Global settings were retained; the updated server starts
  with an empty assistants page.
