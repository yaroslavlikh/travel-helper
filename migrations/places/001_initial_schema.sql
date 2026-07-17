CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE destinations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    country_code CHAR(2),
    center GEOMETRY(Point, 4326),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE destination_profiles (
    destination_id UUID PRIMARY KEY REFERENCES destinations(id),
    summary TEXT,
    source_version TEXT,
    freshness_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE categories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    parent_id UUID REFERENCES categories(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE category_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_name TEXT NOT NULL,
    source_category TEXT NOT NULL,
    category_id UUID NOT NULL REFERENCES categories(id),
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    UNIQUE (source_name, source_category)
);

CREATE TABLE tags (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL
);

CREATE TABLE sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    base_url TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE import_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id UUID NOT NULL REFERENCES sources(id),
    destination_id UUID NOT NULL REFERENCES destinations(id),
    scope JSONB NOT NULL,
    source_version TEXT,
    checksum TEXT NOT NULL,
    manifest JSONB NOT NULL,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    received_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    merged_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    rejection_reasons JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE places (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    destination_id UUID NOT NULL REFERENCES destinations(id),
    canonical_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    category_id UUID REFERENCES categories(id),
    location GEOMETRY(Point, 4326) NOT NULL,
    address TEXT,
    website TEXT,
    phone TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('staged', 'active', 'inactive')),
    deleted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX places_destination_status_idx ON places(destination_id, status) WHERE deleted_at IS NULL;
CREATE INDEX places_location_gix ON places USING GIST(location);
CREATE INDEX places_normalized_name_idx ON places(destination_id, normalized_name);

CREATE TABLE place_names (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id UUID NOT NULL REFERENCES places(id),
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    language_code TEXT NOT NULL DEFAULT 'und',
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    source_id UUID REFERENCES sources(id),
    UNIQUE (place_id, normalized_name, language_code)
);

CREATE TABLE place_tags (
    place_id UUID NOT NULL REFERENCES places(id),
    tag_id UUID NOT NULL REFERENCES tags(id),
    value BOOLEAN NOT NULL DEFAULT TRUE,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    source_kind TEXT NOT NULL,
    source_version TEXT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (place_id, tag_id, source_version)
);

CREATE TABLE place_source_records (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id UUID NOT NULL REFERENCES places(id),
    source_id UUID NOT NULL REFERENCES sources(id),
    external_id TEXT NOT NULL,
    source_url TEXT,
    source_category TEXT,
    source_payload JSONB NOT NULL,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at TIMESTAMPTZ,
    UNIQUE (source_id, external_id)
);
CREATE INDEX place_source_records_place_idx ON place_source_records(place_id);

CREATE TABLE place_source_snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_source_record_id UUID NOT NULL REFERENCES place_source_records(id),
    import_run_id UUID NOT NULL REFERENCES import_runs(id),
    checksum TEXT NOT NULL,
    payload JSONB NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (place_source_record_id, checksum)
);

CREATE TABLE place_features (
    place_id UUID PRIMARY KEY REFERENCES places(id),
    popularity DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (popularity BETWEEN 0 AND 1),
    tourist_relevance DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (tourist_relevance BETWEEN 0 AND 1),
    uniqueness_score DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (uniqueness_score BETWEEN 0 AND 1),
    localness DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (localness BETWEEN 0 AND 1),
    freshness DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (freshness BETWEEN 0 AND 1),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (confidence BETWEEN 0 AND 1),
    tourist_trap_risk DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (tourist_trap_risk BETWEEN 0 AND 1),
    source_quality DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (source_quality BETWEEN 0 AND 1),
    version TEXT NOT NULL,
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE place_embeddings (
    place_id UUID NOT NULL REFERENCES places(id),
    model_version TEXT NOT NULL,
    embedding vector(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (place_id, model_version)
);
CREATE INDEX place_embeddings_vector_idx ON place_embeddings USING hnsw (embedding vector_cosine_ops);

CREATE TABLE place_images (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id UUID NOT NULL REFERENCES places(id),
    source_id UUID NOT NULL REFERENCES sources(id),
    source_url TEXT NOT NULL,
    image_url TEXT NOT NULL,
    license TEXT NOT NULL,
    attribution TEXT NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    width INTEGER,
    height INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (place_id, source_url)
);

CREATE TABLE user_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL CHECK (event_type IN ('place_impression', 'place_opened', 'place_saved', 'place_hidden', 'place_selected', 'external_link_clicked', 'plan_regenerated', 'place_feedback_submitted')),
    session_id TEXT NOT NULL,
    place_id UUID REFERENCES places(id),
    retrieval_id UUID,
    position INTEGER,
    ranking_version TEXT,
    experiment_variant TEXT,
    filters JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX user_events_place_idx ON user_events(place_id, created_at DESC);

CREATE TABLE place_stats_daily (
    place_id UUID NOT NULL REFERENCES places(id),
    day DATE NOT NULL,
    impressions INTEGER NOT NULL DEFAULT 0,
    opened INTEGER NOT NULL DEFAULT 0,
    saved INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (place_id, day)
);
