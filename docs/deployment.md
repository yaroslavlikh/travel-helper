# Closed-beta deployment

This runbook is for one explicitly labelled demo/staging instance. It does not make fixture
recommendations, unavailable pricing or unknown entry rules into production facts.

## Required platform resources

- One HTTPS web service with a stable hostname.
- Managed PostgreSQL/PostGIS/pgvector for the places catalog and application state. Configure
  `DATABASE_URL` with Render's internal database URL; it is required for staging and production.
- A secret manager for all credentials; do not put secrets in images, repository files or logs.

## Configuration

Start from `.env.example`. For closed demo use `APP_ENV=staging` and `DEMO_MODE=true`; show the
demo/data warnings to every tester. For production, `DEMO_MODE=false`, `TRUSTED_HOSTS` must contain
the real hostname, account cookies require HTTPS and `AUTH_SESSION_SECRET` must be at least 32
characters. Keep `CORS_ALLOWED_ORIGINS` empty when the static UI is served by this same application.

Rotate any credential that was ever shared outside the secret manager before the first deployment.

## Browser integrations

Do not inject partner or tracking scripts into the planning page. They can intercept DOM APIs and
break chat initialisation, guest history and recommendation requests. Affiliate routing belongs in
the server-owned outbound links and event endpoint, where it is observable and can fail safely.

## Release sequence

1. Run `make check` from the commit being deployed.
2. Build the image: `docker build -t tudavai:<sha> .`.
3. Run application migrations and set up the LangGraph checkpointer with the same image:
   `python scripts/migrate_app.py`, `python scripts/setup_langgraph_postgres.py`, then
   `python scripts/check_app_database.py`.
4. Run catalog migrations with `PLACES_DATABASE_URL`: `python scripts/migrate_places.py`.
5. Seed identity only once catalog migrations are successful: `python scripts/bootstrap_global_catalog.py`.
   This writes 60 countries as `draft`; it does not publish recommendation candidates.
6. Deploy the application. Local SQLite paths are development-only and do not need a production volume.
7. Check `/health/live` for process liveness. `/health/ready` may remain `degraded` until live
   pricing providers are configured; do not treat that as a successful public-pricing launch.
8. Smoke-test a guest recommendation, login/logout (if enabled), and an unavailable-POI response.

## Rollback

Keep the previous image and database backup. Roll back the web image first. SQL migrations are
additive; do not delete schema or data as a rollback shortcut. Disable a failing provider with its
feature flag and return an explicit partial result instead.

## Before public beta

- Replace process-local rate limiting with edge or shared-store limiting.
- Define retention/deletion policy and Langfuse sampling/content capture policy.
- Import and evaluate at least Istanbul plus Phuket or Kuala Lumpur through the generic POI path.
- Connect evidence-backed candidate search, entry and pricing providers before claiming live facts.
