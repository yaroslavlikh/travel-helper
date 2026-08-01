# ADR-0029: PostgreSQL application state outside local development

- Status: accepted
- Date: 2026-08-01

## Context

The places catalog already uses managed PostgreSQL, while accounts, chat snapshots, feedback,
product events and LangGraph checkpoints were split between SQLite and process memory. That state is
lost or unsafe across public-service restarts and replicas.

## Decision

`DATABASE_URL` is required for staging and production and points to the same managed PostgreSQL
instance as the places catalog. Application-owned data lives only in the separate `app` schema:
accounts, hashed application sessions, account chats, feedback and product events. Ordered additive
SQL files in `migrations/app/` are recorded in `app.schema_migrations` under an advisory lock.

Staging and production use `AsyncConnectionPool`, `PostgresAccountStore`, PostgreSQL event stores
and `AsyncPostgresSaver`. Startup verifies PostgreSQL connectivity; readiness separately reports
whether app migrations and checkpoint tables are available. The setup command for LangGraph is
repeatable. Local development retains SQLite and bounded in-memory telemetry; tests use an isolated
in-memory checkpointer and store.

## Consequences

- No application migration reads, writes or removes tables in the places schema.
- Session tokens remain hashes and password verifiers remain salted `scrypt` values.
- Deleting an account cascades database-owned sessions and chats; the API then deletes matching
  LangGraph threads.
- Rollback means deploying the previous compatible app image. Migrations are additive; no schema or
  data deletion is used as a rollback mechanism.
