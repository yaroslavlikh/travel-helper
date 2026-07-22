# ADR-0012: Optional OIDC accounts with server-side chat ownership

- Status: accepted
- Date: 2026-07-18

## Context

Anonymous chat presentation state currently lives in browser `localStorage`, while LangGraph state is
addressed by a caller-provided random `session_id`. This is sufficient for one browser, but it cannot
provide cross-device history or prove that a caller owns a thread.

Accounts must remain optional. A guest must be able to complete the full recommendation flow without
registration, and losing account-provider availability must not disable anonymous planning.

## Decision

Use a provider-neutral OpenID Connect authorization-code flow with PKCE for external providers and an
optional local email/password flow. Both complete by issuing the same opaque random application session
in an `HttpOnly`, `SameSite=Lax` cookie. Only hashes of application sessions are stored. A local password
is stored only as a salted `hashlib.scrypt` verifier; external access tokens are never persisted.

The first local flow supports registration and login with a normalized email address and a minimum
12-character password. It intentionally does not pretend to verify an email address or send password
reset messages until a transactional email provider is configured. Public deployment must put a rate
limit in front of the password endpoints and set a 32+-character `AUTH_SESSION_SECRET`; development may
use a process-local session secret so the flow remains testable without committing a secret.

Authenticated chat presentation snapshots are stored server-side and indexed by the stable OIDC
`issuer + subject` identity. Every account chat operation checks ownership. An authenticated request may
continue only an existing owned chat; knowing another `session_id` never grants access.

Guest browser history remains separate. After the first login the UI explicitly offers to import it.
Import creates new owned thread IDs and uses a per-account client import ID for idempotency. Existing
anonymous checkpointer threads are not claimed because old clients have no possession secret that can
prove ownership. Local data is retained until every selected import succeeds.

Authentication starts on a dedicated `/login` page that explains what is stored, keeps guest use as
an equal choice, and offers either email/password or a configured provider redirect. The main workspace exposes an explicit sync state; authenticated presentation
snapshots are cached immediately in the browser and flushed to the owned server record on a short
debounce and when the document becomes hidden.

The browser keeps a local cache for responsive rendering, but authenticated server storage is canonical.
Deleting a chat removes its account snapshot and associated LangGraph thread state where the configured
checkpointer supports deletion. Account deletion removes all owned snapshots and application sessions;
the external OIDC identity remains managed by its provider.

## Security and privacy

- Mutating authenticated requests require a session-bound CSRF token.
- Redirect targets are restricted to local absolute paths.
- OIDC state and PKCE verifier are integrity-protected, short-lived, and never stored in URLs after the
  callback.
- Passwords are accepted only by the dedicated login endpoints, never logged, and compared against a
  salted `scrypt` verifier with `hmac.compare_digest`.
- No raw chat content is placed in authentication cookies or logs.
- Account APIs return only resources owned by the current identity.
- An unauthenticated request with an account-owned chat ID receives the same `404` as an unknown
  planning session; IDs do not become a fallback bearer credential for the anonymous graph.
- Production requires HTTPS cookies and a non-default application signing secret.

## Consequences

- Google and other conforming OIDC providers can be selected by configuration without changing domain
  or chat storage contracts.
- Local development and tests can run with authentication disabled; account repositories remain directly
  testable without external network access.
- The first account store uses SQLite locally. The repository boundary permits a PostgreSQL adapter before
  public multi-worker deployment.
- Imported presentation history is preserved, but an old anonymous graph checkpoint is intentionally not
  attached to the account.

## Rejected alternatives

- Treat `session_id` as proof of ownership: bearer identifiers leak through browser storage, traces, and
  support screenshots and do not provide adequate authorization.
- Store password-reset or email-verification tokens before an outbound email provider exists: a token that
  cannot be delivered is not a recovery flow.
- Automatically upload local history at login: chat text can contain personal data, so migration requires
  an explicit user action.
