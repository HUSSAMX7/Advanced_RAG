# Production readiness design interview

Status: first feature implemented and verified locally; live sign-in setup and
user review pending. Later production architecture branches remain open.
Started: 2026-10-13.

## Objective

Design production operation for large uploads, durable processing jobs, shared
persistent data, and concurrent document retrieval and file downloads. Record
agreed domain terms in CONTEXT.md and consequential architecture decisions in
docs/adr/ as the interview resolves them.

## Verified local baseline

- Uploads pass through FastAPI and are copied to local disk in 1 MiB blocks
  (src/advanced_rag/web/files/services.py, upload). The default limit is 50 MiB per file
  (src/advanced_rag/config.py:40). Downloads use FileResponse
  (src/advanced_rag/web/files/routes.py, download).
- File metadata and processing status already live in SQLite, separately from
  original file bytes (src/advanced_rag/web/files/repository.py).
- Conversation history lives in JSON files
  (src/advanced_rag/agent/sessions.py:30).
- One application process owns the data directory, enforced with .app.lock
  (src/advanced_rag/web/app.py, workspace lifespan).
- Training runs as in-process asyncio tasks. Queued status is persisted in
  SQLite; startup reschedules queued files and marks interrupted running work
  failed (src/advanced_rag/web/files/processing.py, start and train).
- Assistant libraries share an operation lock. Full training holds that lock,
  and retrieval-context acquisition waits for it
  (src/advanced_rag/web/assistants/services.py, get_library;
  src/advanced_rag/web/files/processing.py, _train and context).
- Retrieval uses local FAISS IndexFlatL2 and an in-memory BM25 corpus
  (src/advanced_rag/storage.py:125;
  src/advanced_rag/retrieval/search.py:21).
- Existing domain language distinguishes upload from Training, and Training
  means indexing rather than changing model weights (CONTEXT.md).

## Confirmed requirements

- Sign-in is optional; visitors may use the application as guests.
- Guests have all core functionality, including assistants, files, training and
  chat, and may set their own provider API keys and model settings.
- Every 15 minutes, show the guest a renewal prompt with a suggestion to create
  an account. Renewal keeps the guest workspace. A 60-second no-response grace
  ends in revocation, cancellation and cleanup. Reload retains the session and
  deadline; close/reopen starts fresh, with best-effort close reporting and
  server expiry as fallback. Each guest tab has an independent workspace.
- Guest data is discarded rather than transferred into an account on sign-in.
  A new account starts without the guest's assistants, files or conversations.
  Signing in to an existing account must expose only that account's data.
- Signed-in users own private data. There are no team/shared libraries.
- Sign-in uses only an email verification message, without a password. The
  initial implementation sends a verification link, as stated before execution.
- Service settings and credentials are private to each account or guest
  session. Users may set their own OpenAI/LlamaParse keys and model preferences;
  one owner's updates must not change another owner's runtime settings.
- Account provider keys persist encrypted. Guests' keys are deleted with their
  sessions. Users supply their own keys; missing keys return service-specific
  guidance rather than using server credentials.
- File preparation may wait in the background. The user should receive a
  meaningful notice when server load delays processing.
- Delivery is one feature at a time. Implement and verify that feature, present
  it for review, and wait for the user's explicit approval before starting the
  next implementation feature. This gate was explicitly requested by the user.

## Reported environment and unresolved capacity

The user has a Supabase account only; no project or services have been configured.
The baseline application used local SQLite, files and FAISS without Supabase.
Feature 1 adds Supabase Auth integration and owner-specific local workspaces.
Supabase project provisioning is still required for a connected demonstration.
The user has no domain or SMTP provider. Backend and frontend hosting remain
undecided; nothing has been deployed or purchased.

Traffic and file-volume estimates are unknown. Establish configurable admission
and concurrency limits, then measure representative ingestion and retrieval
workloads. Example worker counts or queue lengths are illustrations, not capacity
promises. Watch memory, CPU, job duration, queue age, search latency, database load,
and upstream model/OCR rate limits before raising concurrency.

## Current decision frontier

Provision the external sign-in services, validate real email delivery, and review
Feature 1 with the user before beginning the next implementation feature. See
[Feature 1](identity-and-guest-sessions.md). Capacity and hosting decisions remain
open for their subsequent design rounds.

Questions dependent on these answers wait until their prerequisites are settled.

## Proposed review sequence

This sequence is a proposal, not authorization to implement every feature now.

1. Identity and access: optional sign-in, renewable guest behavior, ownership
   checks and isolated owner-specific settings needed to exercise the existing
   application safely. Full database/file/queue migration remains separate.
2. Durable application records: assistants, conversations and document metadata.
3. File lifecycle: private storage, uploads, resumability and downloads.
4. Durable background preparation: jobs, worker execution, progress, retries and
   cancellation.
5. Concurrent retrieval: indexed content, publication and read isolation.
6. Capacity and operations: measured limits, overload behavior, monitoring,
   backups and recovery validation.

Each feature must declare prerequisites and deliver a reviewable working scope.
If one feature requires an earlier infrastructure change, adjust its scope and
sequence explicitly instead of silently implementing later features.

## Subsequent branches

After their prerequisites are settled, resolve file versus document identity,
versions and duplicate uploads; upload completion and resumability; processing
states, retries, cancellation and publication; authorization and isolation;
database, object storage and retrieval backend choices; queue delivery and worker
ownership; read scaling and resource limits; deletion and source availability;
backups, recovery and migration; observability and rollout acceptance criteria.

## References checked

[MDN pagehide documentation](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event)
states that page closure notifications are not reliable, particularly on mobile.
Immediate server-side deletion on every browser close cannot be guaranteed.
Explicit session exit can revoke access and initiate deletion; missed closures
need an agreed server-side expiration and cleanup mechanism. Cleanup must cover
originals, derived images, indexes, assistants, conversations and outstanding
processing work. A best-effort browser signal alone does not satisfy this policy.

[Supabase passwordless email authentication](https://supabase.com/docs/guides/auth/auth-email-passwordless)
supports emailed verification codes and links. For verification delivery to
arbitrary email addresses, configure a production email sending service;
[the default Supabase SMTP service](https://supabase.com/docs/guides/auth/auth-smtp)
is restricted to project team addresses. Email delivery setup is a prerequisite
for validating the confirmed any-email sign-in requirement.

Supabase Auth is integrated for Feature 1. Its other services remain candidates
for later reviewed features. Documented capabilities include
[Auth](https://supabase.com/docs/guides/auth),
[resumable file uploads](https://supabase.com/docs/guides/storage/uploads/resumable-uploads),
[Postgres-based durable queues](https://supabase.com/docs/guides/queues), and
[pgvector](https://supabase.com/docs/guides/ai/vector-columns).
Queue delivery does not itself execute Python processing or guarantee a job's
side effects happen only once; worker execution and safe retries need explicit
design. Separate application records from original file storage, and enqueue
references to processing work rather than complete file bytes.

The platform's
[anonymous sign-in](https://supabase.com/docs/guides/auth/auth-anonymous)
creates a persisted anonymous auth user; it does not automatically enforce the
product requirement for temporary guest data. Guest expiration and cleanup must
be designed if temporary storage is allowed.

## First-feature implementation facts

Each owner's SettingsState stores its own settings.json. Provider credentials
use Fernet when WEB_CREDENTIAL_ENCRYPTION_KEY is configured, with Windows
user-scoped DPAPI retained for existing local installations
(src/advanced_rag/web/settings/credentials.py). The settings services update
that owner's assistant libraries and enforce owner-specific busy/index checks
(src/advanced_rag/web/settings/services.py). The identity gateway isolates owner
storage and runtime values. Linux hosting must configure the portable encryption
key; live deployment and distributed processing remain later work.

[Amazon S3 multipart upload overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpuoverview.html)
describes uploading parts independently, retrying failed parts, and pausing and
resuming uploads. This is an option to evaluate after workload and hosting
constraints are agreed; it does not select AWS as the deployment provider.
