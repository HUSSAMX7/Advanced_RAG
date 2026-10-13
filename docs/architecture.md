# Agreed code organization

The web backend now uses feature packages and plain functions for application
operations and persistence. This structure also applies to new implementation.
The ingestion, retrieval and agent packages retain their existing boundaries.

```text
src/advanced_rag/
├── web/
│   ├── app.py
│   ├── dependencies.py
│   ├── state.py
│   ├── errors.py
│   ├── system.py
│   ├── identity/
│   │   ├── routes.py
│   │   ├── schemas.py
│   │   ├── services.py
│   │   ├── repository.py
│   │   ├── dependencies.py
│   │   ├── providers.py
│   │   └── gateway.py
│   ├── assistants/     # routes.py, schemas.py, services.py, repository.py
│   ├── files/          # same feature files, plus processing.py
│   ├── conversations/  # routes.py, schemas.py, services.py, repository.py
│   └── settings/       # same feature files, plus credentials.py
├── ingestion/
└── retrieval/
```

Within each feature, routes.py handles HTTP input, invokes the operation and
returns a response; schemas.py defines request and response models; services.py
owns the feature's rules and orchestration; repository.py owns persistent reads
and writes. Add feature helpers such as converters.py when needed. A small
feature only needs the files that serve actual responsibilities.

app.py creates FastAPI, registers routers and wires application startup/shutdown.
Use dependencies.py for request dependency resolution. HTTP route handlers
delegate feature behavior rather than accumulating processing or SQL logic.

Use plain functions with explicit dependencies as the default for feature
operations and persistence. Classes are justified by concrete requirements such
as Pydantic models or framework contracts, or a cohesive state/lifecycle whose
implementation benefits from an object; explain the need when introducing one.
Functions sharing a dependency do not by themselves require a wrapper class.

The additional files serve concrete responsibilities:

- files/processing.py handles training, cancellation, atomic index publication,
  recovery and the retrieval cache. The file services handle upload rules,
  credentials required before training, downloads and source URLs.
- identity/providers.py verifies Supabase tokens. gateway.py forwards an
  authenticated request to its owner's application; dependencies.py resolves
  identity for the authentication routes.
- settings/credentials.py encrypts provider keys with Fernet or local Windows
  DPAPI. repository.py owns the atomic settings JSON reads and writes.
- state.py carries workspace locks and title tasks shared across features.
  errors.py translates domain errors into HTTP responses. system.py contains
  the health route, which needs no persistence layer.

Remaining classes have concrete needs: Pydantic models validate framework
inputs; TypedDicts describe record contracts; dataclasses group runtime locks,
tasks, caches and their owning settings without business methods; exception
types distinguish failures; ctypes.Structure defines the Windows DPAPI binary
contract. OwnerGateway is a callable ASGI adapter because Starlette treats a
plain function endpoint as an HTTP request handler. Its only operation delegates
to the dispatch function.

The HTTP paths and public create_app factory are preserved. Internal imports
now use the feature packages; the former Library, Assistants, Registry,
WebSettings, Owners and SupabaseVerifier operation wrappers were removed.
SQLite records, uploads, indexes, conversations and encrypted settings retain
their existing storage formats and paths. This refactor does not introduce a
database migration or distributed job queue.

Validation: the complete local suite passed with 131 tests after the refactor,
along with Ruff and type checks for the web/config modules. These tests use
mock providers and temporary storage; live Supabase email delivery remains a
separate setup step.

Make restructuring reviewable within the current feature. Preserve behavior and
validate affected interfaces; document any incomplete transition clearly.
