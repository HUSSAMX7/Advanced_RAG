# Feature 1: optional sign-in and renewable guest workspaces

Status: implemented locally; Supabase connected on 2026-10-13 and a real
email-link request accepted. Email receipt, completed sign-in and final review pending.

Arabic setup walkthrough: [إعداد الدخول بالإيميل](../setup-email-signin.md).

## Agreed behavior

- Sign-in is optional. Email verification is the only sign-in method; no password
  or Google account is required. The initial UI sends a one-time verification
  link in the email.
- Every registered account owns a private set of assistants, libraries,
  conversations, provider credentials and model choices. There is no sharing.
- A guest has the same application functions in a temporary workspace. After
  15 minutes, a renewal prompt appears with a 60-second countdown. Renewal starts
  another 15-minute period. Requests and navigation do not automatically renew.
- Explicit exit or expiry revokes guest access immediately. Active requests are
  cancelled; title and training tasks are stopped/awaited before data cleanup.
- Reloading a tab retains its guest workspace and existing deadlines. A newly
  opened/restored tab starts fresh. Guest workspaces are independent across tabs.
- Closing a tab sends a best-effort close notice. The server grants 15 seconds
  for reload recovery, then revokes and purges it. If no notice arrives, the
  original 15-minute deadline and 60-second grace bound the session lifetime.
  Browser close detection cannot guarantee instantaneous physical deletion.
- A successful sign-in discards the guest workspace; guest data and provider
  keys are never copied into the account. Existing accounts keep their own work.
- Users provide their own service keys. The web application does not inherit
  platform/CLI provider credentials. Missing required keys produce an actionable
  Arabic error before starting a chat/title or indexing job.
- Account keys are encrypted at rest and remain available after a restart.
  Guest keys are encrypted while retained and deleted with their workspace.
  Responses expose only configured flags, never the saved key.

## Implementation boundary

The FastAPI backend is organized into feature packages as described in
[the architecture guide](../architecture.md). Identity operations are functions
in identity/services.py; guest metadata persistence lives in
identity/repository.py and Supabase verification in identity/providers.py.

The identity gateway resolves an opaque guest token or a Supabase bearer token,
then selects an isolated instance of the existing workspace application. Verified
account identity is checked server-side with Supabase Auth `/auth/v1/user`;
unverified/anonymous users and client-supplied owner IDs are rejected.

All data routes pass through this boundary, including the legacy unscoped API,
file downloads and source images. The frontend fetches media with the same
credentials instead of placing session tokens in URLs.

Records, files, indexes and conversations still use local storage underneath
`WEB_DATA_DIR/owners/accounts/<id>/` or `owners/guests/<id>/`. Guest deadlines and
revocation live in `identity.sqlite3`. The host still runs one process and retains
the current shared local processing lock. Database/object-storage migration and
distributed workers belong to later reviewed features.

`WEB_IDENTITY_ENABLED=false` explicitly selects the original local application;
it is for local/CLI compatibility and existing baseline tests, not public hosting.
Old root-level application data is left in place and is not automatically copied
to any guest or account.

## Configuration for a connected demonstration

1. Use the existing `HUSSAMX7’s Project` and obtain its URL and **publishable/anon** key.
   Never use a service-role/secret key as the publishable key.
2. Add these values to the ignored `.env` using `.env.example`. Supply
   `WEB_CREDENTIAL_ENCRYPTION_KEY` for portable secret encryption and retain it
   securely across restarts. Without it, Windows uses the existing DPAPI mode;
   portable deployment must configure the encryption key.
3. Enable email authentication in Supabase. Set the Site URL and allowed redirect
   URLs to the actual application origin (for local review, for example
   `http://127.0.0.1:8001/`). Keep the email template's verification link.
4. Configure custom SMTP for verification to arbitrary email addresses. The
   default Supabase sender only sends to project team members and is unsuitable
   for validating the product's any-email requirement.
5. Build the frontend and start the application. Check two different accounts,
   guest-to-account switching, sign-out, reload, close/reopen, and actual email
   delivery. The user has confirmed project creation; Auth/SMTP configuration
   and real email delivery remain unverified until inspected and exercised.

## References

- [Supabase passwordless email authentication](https://supabase.com/docs/guides/auth/auth-email-passwordless)
- [Supabase custom SMTP](https://supabase.com/docs/guides/auth/auth-smtp)
- [Browser pagehide limitations](https://developer.mozilla.org/en-US/docs/Web/API/Window/pagehide_event)

## Validation completed

- The existing 119-test baseline passed alongside the initial identity tests;
  the identity suite now has 12 passing HTTP tests including additional checks
  for public-key configuration and owner-scoped busy/embedding rules.
- Ruff and Python type checks passed for the changed web/config modules; the
  production TypeScript/Vite build passed.
- Browser QA in a disposable local fixture verified guest entry, assistant
  creation, reload preservation, close/reopen isolation, renewal prompt and
  renewal, simulated email-link/PKCE sign-in, encrypted-settings UI persistence,
  sign-out and the absence of inherited account keys in a new guest workspace.
- The email service in that fixture is simulated. No real email delivery or
  external deployment was validated by that fixture.
- Connected setup on 2026-10-13: Supabase Auth settings and local auth config
  returned HTTP 200, and the frontend production build passed. A real email-link
  request through the in-app browser displayed a success notice. This confirms
  request acceptance; email receipt, redirect settings, completed sign-in,
  two-account isolation with real accounts and general SMTP delivery remain
  unverified. The local encryption key was retained and `.env` is ignored by Git.
- Subsequent live email requests returned HTTP 429 with
  `over_email_send_rate_limit`. The frontend now gives quota guidance rather
  than blaming the email address, with errors inside the login form so they are
  accessible within the guest login dialog. Four regression tests passed
  (`npm --prefix frontend run test:auth`) and the frontend build passed. Local
  browser QA replayed the same response in both entry and guest-dialog flows
  using `tests/identity_browser_fixture.py --email-rate-limited`; this sends no
  real email. Debug logging was removed. Real email receipt and sign-in remain
  pending sending availability or SMTP configuration.
