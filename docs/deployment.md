# Closed-beta deployment

This runbook is for one explicitly labelled demo/staging instance. It does not make fixture
recommendations, unavailable pricing or unknown entry rules into production facts.

## Required platform resources

- One HTTPS web service with a stable hostname.
- A persistent volume for the current SQLite checkpoint and account files. Multiple web replicas
  are unsupported until these stores move to managed PostgreSQL.
- Managed PostgreSQL/PostGIS/pgvector for the places catalog when POI search is enabled.
- A secret manager for all credentials; do not put secrets in images, repository files or logs.

## Configuration

Start from `.env.example`. For closed demo use `APP_ENV=staging` and `DEMO_MODE=true`; show the
demo/data warnings to every tester. For production, `DEMO_MODE=false`, `TRUSTED_HOSTS` must contain
the real hostname, account cookies require HTTPS and `AUTH_SESSION_SECRET` must be at least 32
characters. Keep `CORS_ALLOWED_ORIGINS` empty when the static UI is served by this same application.

Rotate any credential that was ever shared outside the secret manager before the first deployment.

## Release sequence

1. Run `make check` from the commit being deployed.
2. Build the image: `docker build -t tudavai:<sha> .`.
3. Run PostgreSQL migrations with the same image and production `PLACES_DATABASE_URL`:
   `python scripts/migrate_places.py`.
4. Seed identity only once migrations are successful: `python scripts/bootstrap_global_catalog.py`.
   This writes 60 countries as `draft`; it does not publish recommendation candidates.
5. Deploy one application replica with persistent paths mounted for `.data/`.
6. Check `/health/live` for process liveness. `/health/ready` may remain `degraded` until live
   pricing providers are configured; do not treat that as a successful public-pricing launch.
7. Smoke-test a guest recommendation, login/logout (if enabled), and an unavailable-POI response.

## Rollback

Keep the previous image and database backup. Roll back the web image first. SQL migrations are
additive; do not delete schema or data as a rollback shortcut. Disable a failing provider with its
feature flag and return an explicit partial result instead.

## Before public beta

- Move chat/account persistence to managed PostgreSQL and remove the single-instance constraint.
- Replace process-local rate limiting with edge or shared-store limiting.
- Define retention/deletion policy and Langfuse sampling/content capture policy.
- Import and evaluate at least Istanbul plus Phuket or Kuala Lumpur through the generic POI path.
- Connect evidence-backed candidate search, entry and pricing providers before claiming live facts.
