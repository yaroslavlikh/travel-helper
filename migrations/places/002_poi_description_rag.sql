CREATE TABLE source_usage_policies (
    source_id UUID PRIMARY KEY REFERENCES sources(id),
    may_store_text BOOLEAN NOT NULL,
    may_embed_text BOOLEAN NOT NULL,
    may_display_excerpt BOOLEAN NOT NULL,
    requires_attribution BOOLEAN NOT NULL DEFAULT TRUE,
    reviewed_at TIMESTAMPTZ NOT NULL,
    review_note TEXT NOT NULL,
    CHECK (may_embed_text = FALSE OR may_store_text = TRUE),
    CHECK (may_display_excerpt = FALSE OR may_store_text = TRUE),
    CHECK (char_length(trim(review_note)) BETWEEN 8 AND 1_000)
);

CREATE TABLE place_description_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    place_id UUID NOT NULL REFERENCES places(id),
    place_source_record_id UUID NOT NULL REFERENCES place_source_records(id),
    source_snapshot_id UUID NOT NULL REFERENCES place_source_snapshots(id),
    language_code TEXT NOT NULL,
    content_kind TEXT NOT NULL CHECK (content_kind IN ('overview', 'practical', 'editorial')),
    text_content TEXT NOT NULL,
    content_checksum TEXT NOT NULL CHECK (content_checksum ~ '^[0-9a-f]{64}$'),
    observed_at TIMESTAMPTZ NOT NULL,
    valid_until TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (char_length(trim(text_content)) BETWEEN 80 AND 1_600),
    CHECK (valid_until IS NULL OR valid_until > observed_at),
    UNIQUE (place_source_record_id, language_code, content_kind)
);
CREATE INDEX place_description_documents_lookup_idx
    ON place_description_documents (place_id, language_code, content_kind, observed_at DESC);

CREATE TABLE place_description_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID NOT NULL REFERENCES place_description_documents(id) ON DELETE CASCADE,
    position SMALLINT NOT NULL CHECK (position >= 0),
    text_content TEXT NOT NULL,
    content_checksum TEXT NOT NULL CHECK (content_checksum ~ '^[0-9a-f]{64}$'),
    token_estimate INTEGER NOT NULL CHECK (token_estimate > 0 AND token_estimate <= 2_000),
    embedding vector(64) NOT NULL,
    embedding_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (char_length(trim(text_content)) BETWEEN 1 AND 600),
    UNIQUE (document_id, position, embedding_version)
);
CREATE INDEX place_description_chunks_vector_idx
    ON place_description_chunks USING hnsw (embedding vector_cosine_ops);
