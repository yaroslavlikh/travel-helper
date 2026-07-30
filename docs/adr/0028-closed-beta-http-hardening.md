# ADR-0028: HTTP hardening for a single-instance closed beta

- Status: accepted
- Date: 2026-07-30

## Context

The application exposes LLM-backed recommendation, destination-chat and password endpoints. It can
run in a container, but had no host allowlist, CORS policy, security headers, request limiting or
container healthcheck. Current checkpoint and account stores are SQLite, so a production deployment
is a single instance with a persistent volume, not a horizontally scalable public service.

## Decision

For a closed beta, add dependency-free HTTP safeguards at the application boundary:

- explicit `TRUSTED_HOSTS`; production rejects the local-only default and wildcard hosts;
- optional explicit `CORS_ALLOWED_ORIGINS`; same-origin remains the default;
- basic browser security headers on every response;
- process-local sliding-window limits for expensive chat/auth endpoints, keyed by direct client IP
  and path; the application does not trust forwarded IP headers itself;
- Docker healthcheck against `/health/live`, plus image contents required to run migrations and
  bootstrap scripts.

The rate limiter is intentionally process-local. It protects a single closed-beta process and makes
abuse visible without adding Redis. A multi-instance or public launch must replace it with an
edge/provider or shared-store limiter.

## Consequences

- Deployers must configure a real host and HTTPS origins before `APP_ENV=production` can start.
- The `staging` + `DEMO_MODE=true` configuration remains valid for an explicitly labelled closed
  demo; it is not a public production recommendation service.
- A durable managed PostgreSQL checkpointer/account store, provider-backed rate limiting, backups,
  retention policy and public pricing/search evidence remain separate launch requirements.
