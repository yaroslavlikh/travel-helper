CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE IF NOT EXISTS app.accounts (
    id UUID PRIMARY KEY,
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    email TEXT,
    display_name TEXT,
    password_hash TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (issuer, subject)
);

CREATE TABLE IF NOT EXISTS app.account_sessions (
    token_hash TEXT PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS account_sessions_expiry_idx ON app.account_sessions(expires_at);

CREATE TABLE IF NOT EXISTS app.account_chats (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL REFERENCES app.accounts(id) ON DELETE CASCADE,
    client_import_id TEXT,
    title TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_id, client_import_id)
);

CREATE INDEX IF NOT EXISTS account_chats_owner_updated_idx
    ON app.account_chats(owner_id, updated_at DESC);
