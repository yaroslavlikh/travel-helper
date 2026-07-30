CREATE TABLE source_registry (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    domain TEXT NOT NULL CHECK (domain IN (
        'geography', 'poi', 'destination', 'entry', 'pricing', 'weather', 'transport', 'other'
    )),
    publisher TEXT NOT NULL,
    source_type TEXT NOT NULL CHECK (source_type IN ('official', 'open_data', 'editorial', 'ugc', 'partner')),
    base_url TEXT,
    quality_tier TEXT NOT NULL CHECK (quality_tier IN ('a', 'b', 'c', 'd')),
    license_code TEXT,
    terms_url TEXT,
    allows_storage BOOLEAN NOT NULL DEFAULT FALSE,
    allows_derived_data BOOLEAN NOT NULL DEFAULT FALSE,
    allows_embeddings BOOLEAN NOT NULL DEFAULT FALSE,
    requires_attribution BOOLEAN NOT NULL DEFAULT TRUE,
    polling_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    status TEXT NOT NULL DEFAULT 'review' CHECK (status IN ('review', 'active', 'disabled', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (allows_embeddings = FALSE OR allows_storage = TRUE)
);
CREATE UNIQUE INDEX source_registry_publisher_domain_idx
    ON source_registry (publisher, domain, source_type);

CREATE TABLE geo_entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    parent_id UUID REFERENCES geo_entities(id),
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'sovereign_country', 'travel_jurisdiction', 'territory', 'admin_region', 'city',
        'resort_area', 'island', 'archipelago', 'national_park', 'ski_resort', 'coast',
        'airport_zone'
    )),
    canonical_name TEXT NOT NULL,
    canonical_name_ru TEXT,
    canonical_name_en TEXT,
    slug TEXT NOT NULL UNIQUE,
    iso2 CHAR(2),
    iso3 CHAR(3),
    wikidata_id TEXT,
    geonames_id BIGINT,
    osm_type TEXT CHECK (osm_type IN ('node', 'way', 'relation')),
    osm_id BIGINT,
    centroid GEOMETRY(Point, 4326),
    boundary GEOMETRY(MultiPolygon, 4326),
    timezone_ids TEXT[] NOT NULL DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'draft', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (iso2 IS NULL OR iso2 ~ '^[A-Z]{2}$'),
    CHECK (iso3 IS NULL OR iso3 ~ '^[A-Z]{3}$'),
    CHECK (osm_type IS NULL OR osm_id IS NOT NULL),
    CHECK (osm_type IS NOT NULL OR osm_id IS NULL)
);
CREATE UNIQUE INDEX geo_entities_iso2_country_idx
    ON geo_entities (iso2) WHERE entity_type = 'sovereign_country' AND iso2 IS NOT NULL;
CREATE UNIQUE INDEX geo_entities_wikidata_idx
    ON geo_entities (wikidata_id) WHERE wikidata_id IS NOT NULL;
CREATE INDEX geo_entities_parent_idx ON geo_entities(parent_id);
CREATE INDEX geo_entities_centroid_gix ON geo_entities USING GIST(centroid);
CREATE INDEX geo_entities_boundary_gix ON geo_entities USING GIST(boundary);

CREATE TABLE geo_aliases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    geo_entity_id UUID NOT NULL REFERENCES geo_entities(id) ON DELETE CASCADE,
    alias TEXT NOT NULL,
    normalized_alias TEXT NOT NULL,
    language_code TEXT,
    alias_type TEXT NOT NULL CHECK (alias_type IN ('official', 'common', 'historical', 'transliteration', 'short_name')),
    is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
    source_registry_id UUID REFERENCES source_registry(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (geo_entity_id, normalized_alias, language_code)
);
CREATE INDEX geo_aliases_lookup_idx ON geo_aliases(normalized_alias);

CREATE TABLE geo_relations (
    from_entity_id UUID NOT NULL REFERENCES geo_entities(id) ON DELETE CASCADE,
    to_entity_id UUID NOT NULL REFERENCES geo_entities(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL CHECK (relation_type IN (
        'located_in', 'part_of', 'served_by_airport', 'near', 'common_gateway_for',
        'day_trip_from', 'same_metro_area', 'same_coast', 'entry_scope', 'currency_scope'
    )),
    source_registry_id UUID REFERENCES source_registry(id),
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (from_entity_id, to_entity_id, relation_type),
    CHECK (from_entity_id <> to_entity_id),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);
CREATE INDEX geo_relations_to_idx ON geo_relations(to_entity_id, relation_type);

ALTER TABLE destinations ADD COLUMN IF NOT EXISTS geo_entity_id UUID REFERENCES geo_entities(id);
CREATE UNIQUE INDEX destinations_geo_entity_idx
    ON destinations(geo_entity_id) WHERE geo_entity_id IS NOT NULL;

ALTER TABLE sources ADD COLUMN IF NOT EXISTS source_registry_id UUID REFERENCES source_registry(id);
CREATE UNIQUE INDEX sources_source_registry_idx
    ON sources(source_registry_id) WHERE source_registry_id IS NOT NULL;

CREATE TABLE destination_domain_support (
    geo_entity_id UUID NOT NULL REFERENCES geo_entities(id) ON DELETE CASCADE,
    domain TEXT NOT NULL CHECK (domain IN (
        'identity', 'entry', 'pricing', 'route', 'weather', 'seasonality', 'areas', 'poi',
        'transport_local', 'transport_intercity', 'itineraries', 'beaches', 'nature', 'ski',
        'food', 'nightlife', 'shopping', 'payments', 'connectivity', 'safety', 'health',
        'laws_customs', 'family', 'accessibility', 'remote_work', 'day_trips', 'events', 'sources'
    )),
    level TEXT NOT NULL CHECK (level IN ('full', 'core', 'limited', 'none')),
    freshness_status TEXT NOT NULL CHECK (freshness_status IN ('fresh', 'aging', 'stale', 'unknown')),
    completeness DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (completeness BETWEEN 0 AND 1),
    source_quality DOUBLE PRECISION NOT NULL DEFAULT 0 CHECK (source_quality BETWEEN 0 AND 1),
    last_verified_at TIMESTAMPTZ,
    warnings JSONB NOT NULL DEFAULT '[]'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (geo_entity_id, domain),
    CHECK (jsonb_typeof(warnings) = 'array')
);

CREATE TABLE source_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_registry_id UUID NOT NULL REFERENCES source_registry(id),
    canonical_url TEXT NOT NULL,
    content_hash TEXT NOT NULL CHECK (content_hash ~ '^[0-9a-f]{64}$'),
    http_status INTEGER CHECK (http_status BETWEEN 100 AND 599),
    retrieved_at TIMESTAMPTZ NOT NULL,
    published_at TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    language_code TEXT,
    raw_storage_uri TEXT,
    parser_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('fetched', 'parsed', 'published', 'rejected', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (canonical_url, content_hash),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);
CREATE INDEX source_documents_registry_retrieved_idx
    ON source_documents(source_registry_id, retrieved_at DESC);

CREATE TABLE evidence_spans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_document_id UUID NOT NULL REFERENCES source_documents(id) ON DELETE CASCADE,
    locator_type TEXT NOT NULL CHECK (locator_type IN ('text', 'html', 'json', 'table', 'api_field', 'manual')),
    locator JSONB NOT NULL,
    quote_hash TEXT NOT NULL CHECK (quote_hash ~ '^[0-9a-f]{64}$'),
    normalized_claim TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX evidence_spans_document_idx ON evidence_spans(source_document_id);

CREATE TABLE knowledge_facts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL REFERENCES geo_entities(id),
    predicate TEXT NOT NULL,
    value_json JSONB NOT NULL,
    unit TEXT,
    scope_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    confidence DOUBLE PRECISION NOT NULL CHECK (confidence BETWEEN 0 AND 1),
    verification_status TEXT NOT NULL CHECK (verification_status IN ('verified', 'provisional', 'conflicting', 'unknown', 'retired')),
    freshness_status TEXT NOT NULL CHECK (freshness_status IN ('fresh', 'aging', 'stale', 'unknown')),
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    checked_at TIMESTAMPTZ NOT NULL,
    created_by TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    supersedes_fact_id UUID REFERENCES knowledge_facts(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (valid_to IS NULL OR valid_from IS NULL OR valid_to > valid_from)
);
CREATE INDEX knowledge_facts_subject_predicate_idx
    ON knowledge_facts(subject_entity_id, predicate, checked_at DESC);

CREATE TABLE fact_evidence (
    fact_id UUID NOT NULL REFERENCES knowledge_facts(id) ON DELETE CASCADE,
    evidence_span_id UUID NOT NULL REFERENCES evidence_spans(id) ON DELETE CASCADE,
    support_type TEXT NOT NULL CHECK (support_type IN ('supports', 'conflicts', 'supersedes', 'derived_from')),
    source_weight DOUBLE PRECISION NOT NULL CHECK (source_weight > 0 AND source_weight <= 1),
    PRIMARY KEY (fact_id, evidence_span_id)
);

CREATE TABLE fact_conflicts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    subject_entity_id UUID NOT NULL REFERENCES geo_entities(id),
    predicate TEXT NOT NULL,
    fact_ids UUID[] NOT NULL,
    conflict_type TEXT NOT NULL CHECK (conflict_type IN ('value', 'scope', 'freshness', 'source_authority')),
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    resolution_status TEXT NOT NULL DEFAULT 'open' CHECK (resolution_status IN ('open', 'resolved', 'accepted_unknown')),
    resolution_note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at TIMESTAMPTZ,
    CHECK (cardinality(fact_ids) >= 2),
    CHECK ((resolution_status = 'open') = (resolved_at IS NULL))
);
CREATE INDEX fact_conflicts_open_idx
    ON fact_conflicts(subject_entity_id, predicate) WHERE resolution_status = 'open';

CREATE TABLE knowledge_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES geo_entities(id),
    destination_entity_id UUID REFERENCES geo_entities(id),
    domain TEXT NOT NULL,
    chunk_type TEXT NOT NULL,
    language_code TEXT NOT NULL,
    text_content TEXT NOT NULL CHECK (char_length(trim(text_content)) > 0),
    text_hash TEXT NOT NULL CHECK (text_hash ~ '^[0-9a-f]{64}$'),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    source_document_ids UUID[] NOT NULL,
    evidence_span_ids UUID[] NOT NULL,
    derived_from_fact_ids UUID[] NOT NULL DEFAULT '{}',
    fts TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', text_content)) STORED,
    valid_until TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published', 'retired')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (entity_id, language_code, chunk_type, text_hash),
    CHECK (cardinality(source_document_ids) > 0),
    CHECK (cardinality(evidence_span_ids) > 0)
);
CREATE INDEX knowledge_chunks_destination_idx
    ON knowledge_chunks(destination_entity_id, domain, status) WHERE status = 'published';
CREATE INDEX knowledge_chunks_fts_idx ON knowledge_chunks USING GIN(fts);
