# Private original document storage

Implemented on 2026-10-21 as one reviewable feature. The user requested a fresh
start: delete local application data, preserve source code and keys, and do not
migrate old records. Automatic execution review blocked permanent deletion
with the generic reason "blocked by policy". The safer completed alternative
isolates the old data in an ignored archive and creates a fresh active workspace.
Supabase Auth configuration remains intact.

## Configuration

Server-only settings in the ignored `.env`:

```dotenv
RAG_SUPABASE_URL=https://your-project.supabase.co
RAG_SUPABASE_SECRET_KEY=
RAG_SUPABASE_BUCKET=documents
RAG_SUPABASE_TIMEOUT_SECONDS=30
RAG_MAX_UPLOAD_BYTES=20971520
```

Run `uv run python scripts/configure_storage.py` to create a missing private
bucket and check it. Existing public buckets are rejected rather than modified.
The new bucket has a 20 MiB object limit with these settings. Existing bucket
limits are not altered. The application also enforces its configured upload limit.
The secret is a Pydantic SecretStr, is used only by the server via the `apikey`
header and is excluded from frontend configuration and settings responses.
Omitting both storage credentials retains the original local backend.

## Request flow

1. `files/routes.py` receives the upload and delegates to `files/services.py`.
2. The service validates format, size and PDF signature while staging bytes
   locally, then `files/object_storage.py` uploads them to the private bucket.
3. Only a successful remote upload creates a local file record. Failed or
   cancelled uploads attempt to remove their remote object and local staging file.
4. Download and training resolve the original through object_storage. A missing
   local cache is restored atomically from the authenticated remote endpoint.
5. Unindexing retains the original. File deletion removes the remote original
   before deleting its local record. A remote failure preserves deletion intent
   for retry on restart. Assistant and guest cleanup removes its entire prefix.

Keys use verified identities and server-generated assistant/file identifiers:
`owners/accounts/<id>/assistants/<id>/uploads/<file-id>.<extension>`.
Guests use `owners/guests/<id>/...`. Legacy local mode uses `local/...`.
No public or signed URLs are sent to the browser. Existing authenticated API
routes serve downloads after owner and assistant checks. Blocking storage work
runs in threads; cancellation drains upload/download work before owner cleanup.

## Validation and limits

Tests cover cache loss before download/training, unindex/delete behavior,
failures and deletion recovery, assistant isolation, cleanup of more than 100
objects, guest/account cleanup isolation, cancellation and secret redaction.
A live Supabase upload, cache-free download and deletion were verified; test
objects were removed afterward.

This feature moves original document bytes only. Assistant/file metadata is
still SQLite, conversations and encrypted settings are still JSON, and FAISS
and extracted images remain local. The server still uses one process. Losing
the local record database is not yet recoverable from Storage alone. Uploads
are standard uploads through the backend, without resumability. An abrupt
process termination or an ambiguous remote failure can leave an orphan object;
whole-assistant/guest cleanup removes these objects. No historical data was
uploaded to Supabase, and no remote Auth accounts were deleted.

The fresh active workspace preserves `.env` and encrypted provider keys only.
Keys from active local/account settings are restored with default preferences.
Old storage and CLI sessions remain at the ignored local archive
`output/local-data-before-reset-20261021/`; they were not permanently deleted
or uploaded. Old guest sessions are not restored. The archive contains private
data and credentials and must remain outside version control.

Supabase references: [API keys](https://supabase.com/docs/guides/api/api-keys),
[private downloads](https://supabase.com/docs/guides/storage/serving/downloads),
[Storage API](https://supabase.github.io/storage/).

Next review feature: shared persistent application records in Supabase Postgres.
It requires creating a schema; the supplied server API key provides Data API
and Storage access, while SQL schema provisioning needs a separate supported
administrative path. No new application tables were created in this feature.
