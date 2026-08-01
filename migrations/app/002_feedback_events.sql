CREATE TABLE IF NOT EXISTS app.feedback_events (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    destination_id TEXT,
    value TEXT NOT NULL CHECK (value IN ('up', 'down')),
    comment TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS feedback_events_request_idx
    ON app.feedback_events(request_id, created_at DESC);

CREATE TABLE IF NOT EXISTS app.product_events (
    id UUID PRIMARY KEY,
    session_id TEXT NOT NULL,
    request_id TEXT NOT NULL,
    destination_id TEXT NOT NULL,
    rank INTEGER NOT NULL CHECK (rank > 0),
    provider TEXT NOT NULL CHECK (provider IN ('aviasales', 'yandex_travel')),
    link_kind TEXT NOT NULL CHECK (link_kind IN ('flight', 'stay')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS product_events_request_idx
    ON app.product_events(request_id, created_at DESC);
