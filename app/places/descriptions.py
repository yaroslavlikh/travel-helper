"""Reviewed POI description manifests and their provenance-preserving import path."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Any, Literal
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.places.semantics import deterministic_embedding, vector_literal

if TYPE_CHECKING:
    import psycopg

LOGGER = logging.getLogger(__name__)

DescriptionKind = Literal["overview", "practical", "editorial"]
_SOURCE_SLUG_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_OSM_EXTERNAL_ID_PATTERN = re.compile(r"^(?:node|way|relation)/[1-9][0-9]*$")
_LANGUAGE_CODE_PATTERN = re.compile(r"^[a-z]{2,3}(?:-[A-Z]{2})?$")
_CONTROL_CHAR_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SENTENCE_BOUNDARY_PATTERN = re.compile(r"(?<=[.!?…])\s+")
_MAX_DOCUMENT_CHARS = 1_600
_MAX_CHUNK_CHARS = 480


class DescriptionUsagePolicy(BaseModel):
    """Recorded permission for text reuse; all three capabilities are required for this slice."""

    model_config = ConfigDict(extra="forbid")

    may_store_text: bool
    may_embed_text: bool
    may_display_excerpt: bool
    requires_attribution: bool = True
    reviewed_at: datetime
    review_note: Annotated[str, Field(min_length=8, max_length=1_000)]

    @field_validator("review_note")
    @classmethod
    def normalize_review_note(cls, value: str) -> str:
        return " ".join(value.split())

    @model_validator(mode="after")
    def require_rag_permissions(self) -> DescriptionUsagePolicy:
        if not (self.may_store_text and self.may_embed_text and self.may_display_excerpt):
            raise ValueError(
                "POI description imports require explicit permission to store, embed and "
                "display text"
            )
        return self


class DescriptionSourceInput(BaseModel):
    """A reviewed content source, including the licence decision behind the import."""

    model_config = ConfigDict(extra="forbid")

    slug: Annotated[str, Field(min_length=2, max_length=63)]
    name: Annotated[str, Field(min_length=2, max_length=200)]
    license: Annotated[str, Field(min_length=2, max_length=300)]
    attribution: Annotated[str, Field(min_length=2, max_length=500)]
    base_url: Annotated[str, Field(min_length=8, max_length=2_000)]
    usage_policy: DescriptionUsagePolicy

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if not _SOURCE_SLUG_PATTERN.fullmatch(normalized):
            raise ValueError("source slug must be lowercase letters, digits and hyphens")
        return normalized

    @field_validator("name", "license", "attribution")
    @classmethod
    def normalize_single_line_text(cls, value: str) -> str:
        return " ".join(value.split())

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        return _validated_public_url(value)


class DescriptionDocumentInput(BaseModel):
    """One attributed document for a POI that is already present in the OSM catalog."""

    model_config = ConfigDict(extra="forbid")

    source_external_id: Annotated[str, Field(min_length=2, max_length=300)]
    source_url: Annotated[str, Field(min_length=8, max_length=2_000)]
    place_osm_external_id: Annotated[str, Field(min_length=6, max_length=50)]
    language_code: Annotated[str, Field(min_length=2, max_length=8)] = "ru"
    content_kind: DescriptionKind = "overview"
    text: Annotated[str, Field(min_length=80, max_length=_MAX_DOCUMENT_CHARS)]
    observed_at: datetime
    valid_until: datetime | None = None

    @field_validator("source_external_id")
    @classmethod
    def normalize_external_id(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if any(character in normalized for character in "\x00\r\n"):
            raise ValueError("source_external_id must be a single printable line")
        return normalized

    @field_validator("source_url")
    @classmethod
    def validate_source_url(cls, value: str) -> str:
        return _validated_public_url(value)

    @field_validator("place_osm_external_id")
    @classmethod
    def validate_place_locator(cls, value: str) -> str:
        if not _OSM_EXTERNAL_ID_PATTERN.fullmatch(value):
            raise ValueError(
                "place_osm_external_id must look like node/123, way/123 or relation/123"
            )
        return value

    @field_validator("language_code")
    @classmethod
    def validate_language_code(cls, value: str) -> str:
        if not _LANGUAGE_CODE_PATTERN.fullmatch(value):
            raise ValueError(
                "language_code must follow a short BCP-47 style code, for example ru or en"
            )
        return value

    @field_validator("text")
    @classmethod
    def normalize_text(cls, value: str) -> str:
        return normalize_description_text(value)

    @field_validator("observed_at", "valid_until")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("observed_at and valid_until must include a timezone")
        return value

    @model_validator(mode="after")
    def validate_freshness_interval(self) -> DescriptionDocumentInput:
        if self.valid_until is not None and self.valid_until <= self.observed_at:
            raise ValueError("valid_until must be later than observed_at")
        return self


class DescriptionManifest(BaseModel):
    """The only accepted non-network input to the first description-import vertical slice."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[1]
    destination: Literal["istanbul"]
    source: DescriptionSourceInput
    documents: list[DescriptionDocumentInput] = Field(min_length=1, max_length=300)

    @model_validator(mode="after")
    def reject_duplicate_source_documents(self) -> DescriptionManifest:
        identifiers = {item.source_external_id for item in self.documents}
        if len(identifiers) != len(self.documents):
            raise ValueError("every source_external_id must appear only once per manifest")
        return self


@dataclass(frozen=True, slots=True)
class DescriptionImportReport:
    """Bounded, content-free import telemetry safe to print in a CI or operator log."""

    run_id: str
    received: int
    accepted: int
    updated: int
    unchanged: int
    expired: int
    rejected: int
    rejection_reasons: dict[str, int]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_description_text(value: str) -> str:
    """Keep plaintext paragraphs while rejecting control bytes and oversized source payloads."""

    if _CONTROL_CHAR_PATTERN.search(value):
        raise ValueError("description text contains unsupported control characters")
    paragraphs = [" ".join(part.split()) for part in value.replace("\r\n", "\n").split("\n\n")]
    normalized = "\n\n".join(part for part in paragraphs if part)
    if not 80 <= len(normalized) <= _MAX_DOCUMENT_CHARS:
        raise ValueError(
            f"description text must be between 80 and {_MAX_DOCUMENT_CHARS} characters"
        )
    return normalized


def split_description_text(value: str, *, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    """Chunk deterministically on sentences, with a bounded fallback for a long sentence."""

    if max_chars < 80 or max_chars > 600:
        raise ValueError("max_chars must be between 80 and 600")
    normalized = normalize_description_text(value)
    sentences = [
        item.strip() for item in _SENTENCE_BOUNDARY_PATTERN.split(normalized) if item.strip()
    ]
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        for fragment in _split_long_text(sentence, max_chars=max_chars):
            candidate = f"{current} {fragment}".strip()
            if current and len(candidate) > max_chars:
                chunks.append(current)
                current = fragment
            else:
                current = candidate
    if current:
        chunks.append(current)
    if not chunks or len(chunks) > 20:
        raise ValueError("description produced an invalid number of chunks")
    return chunks


def _split_long_text(value: str, *, max_chars: int) -> list[str]:
    if len(value) <= max_chars:
        return [value]
    words = value.split()
    parts: list[str] = []
    current = ""
    for word in words:
        if len(word) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(
                word[index : index + max_chars] for index in range(0, len(word), max_chars)
            )
            continue
        candidate = f"{current} {word}".strip()
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = word
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def load_description_manifest(path: Path) -> DescriptionManifest:
    """Validate a local reviewed manifest before it receives database access."""

    if path.suffix.casefold() != ".json":
        raise ValueError("description manifest must be a .json file")
    if not path.is_file():
        raise FileNotFoundError(path)
    return DescriptionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def import_place_descriptions(
    database_url: str,
    manifest: DescriptionManifest,
    *,
    manifest_path: Path,
    embedding_version: str,
) -> DescriptionImportReport:
    """Import reviewed, explicitly reusable POI descriptions without any network access."""

    import psycopg
    from psycopg.rows import dict_row

    started_at = datetime.now(UTC)
    manifest_checksum = _checksum(manifest.model_dump(mode="json"))
    rejection_reasons: Counter[str] = Counter()
    accepted = updated = unchanged = expired = 0
    LOGGER.info(
        "poi_description_import_started received=%s source=%s destination=%s manifest_checksum=%s",
        len(manifest.documents),
        manifest.source.slug,
        manifest.destination,
        manifest_checksum,
    )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.transaction():
            source_id = _upsert_source_with_policy(connection, manifest.source)
            destination_id = _destination_id(connection, manifest.destination)
            osm_source_id = _source_id(connection, "openstreetmap")
            run_id = _create_import_run(
                connection,
                source_id=source_id,
                destination_id=destination_id,
                manifest=manifest,
                manifest_path=manifest_path,
                checksum=manifest_checksum,
                started_at=started_at,
            )
            for document in manifest.documents:
                result = _import_document(
                    connection,
                    document=document,
                    source_id=source_id,
                    osm_source_id=osm_source_id,
                    run_id=run_id,
                    embedding_version=embedding_version,
                )
                if result == "unknown_place":
                    rejection_reasons["unknown_place_osm_external_id"] += 1
                elif result == "source_place_conflict":
                    rejection_reasons["source_external_id_is_bound_to_another_place"] += 1
                elif result == "unchanged":
                    accepted += 1
                    unchanged += 1
                else:
                    accepted += 1
                    updated += int(result == "updated")
                    expired += int(_is_expired(document.valid_until, now=started_at))
            _complete_import_run(
                connection,
                run_id=run_id,
                accepted=accepted,
                rejected=sum(rejection_reasons.values()),
                rejection_reasons=rejection_reasons,
                completed_at=datetime.now(UTC),
            )
    report = DescriptionImportReport(
        run_id=run_id,
        received=len(manifest.documents),
        accepted=accepted,
        updated=updated,
        unchanged=unchanged,
        expired=expired,
        rejected=sum(rejection_reasons.values()),
        rejection_reasons=dict(rejection_reasons),
    )
    LOGGER.info(
        "poi_description_import_completed run_id=%s received=%s accepted=%s updated=%s "
        "unchanged=%s expired=%s rejected=%s source=%s destination=%s",
        report.run_id,
        report.received,
        report.accepted,
        report.updated,
        report.unchanged,
        report.expired,
        report.rejected,
        manifest.source.slug,
        manifest.destination,
    )
    return report


def _validated_public_url(value: str) -> str:
    normalized = value.strip()
    parsed = urlparse(normalized)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
    ):
        raise ValueError("URL must be an absolute http(s) URL without credentials")
    return normalized


def _checksum(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _required_id(row: dict[str, Any] | None) -> str:
    if row is None or "id" not in row:
        raise RuntimeError("Expected database mutation to return an id")
    return str(row["id"])


def _source_id(connection: psycopg.Connection[dict[str, Any]], slug: str) -> str:
    row = connection.execute("SELECT id FROM sources WHERE slug = %s", [slug]).fetchone()
    if row is None:
        raise RuntimeError("Import OSM places before importing POI descriptions")
    return str(row["id"])


def _destination_id(connection: psycopg.Connection[dict[str, Any]], slug: str) -> str:
    row = connection.execute("SELECT id FROM destinations WHERE slug = %s", [slug]).fetchone()
    if row is None:
        raise RuntimeError(f"Destination {slug!r} has not been imported")
    return str(row["id"])


def _upsert_source_with_policy(
    connection: psycopg.Connection[dict[str, Any]], source: DescriptionSourceInput
) -> str:
    source_id = _required_id(
        connection.execute(
            """
            INSERT INTO sources (slug, name, license, attribution, base_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                license = EXCLUDED.license,
                attribution = EXCLUDED.attribution,
                base_url = EXCLUDED.base_url
            RETURNING id
            """,
            [source.slug, source.name, source.license, source.attribution, source.base_url],
        ).fetchone()
    )
    policy = source.usage_policy
    connection.execute(
        """
        INSERT INTO source_usage_policies (
            source_id, may_store_text, may_embed_text, may_display_excerpt,
            requires_attribution, reviewed_at, review_note
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id) DO UPDATE SET
            may_store_text = EXCLUDED.may_store_text,
            may_embed_text = EXCLUDED.may_embed_text,
            may_display_excerpt = EXCLUDED.may_display_excerpt,
            requires_attribution = EXCLUDED.requires_attribution,
            reviewed_at = EXCLUDED.reviewed_at,
            review_note = EXCLUDED.review_note
        """,
        [
            source_id,
            policy.may_store_text,
            policy.may_embed_text,
            policy.may_display_excerpt,
            policy.requires_attribution,
            policy.reviewed_at,
            policy.review_note,
        ],
    )
    return source_id


def _create_import_run(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    source_id: str,
    destination_id: str,
    manifest: DescriptionManifest,
    manifest_path: Path,
    checksum: str,
    started_at: datetime,
) -> str:
    return _required_id(
        connection.execute(
            """
            INSERT INTO import_runs (
                source_id, destination_id, scope, source_version, checksum, manifest,
                started_at, status, received_count
            ) VALUES (%s, %s, %s::jsonb, %s, %s, %s::jsonb, %s, 'running', %s)
            RETURNING id
            """,
            [
                source_id,
                destination_id,
                json.dumps({"city": manifest.destination, "content": "poi_description"}),
                f"description-manifest-v{manifest.schema_version}",
                checksum,
                json.dumps(
                    {
                        "source": manifest.source.name,
                        "license": manifest.source.license,
                        "manifest_path": str(manifest_path),
                        "usage_policy": manifest.source.usage_policy.model_dump(mode="json"),
                    }
                ),
                started_at,
                len(manifest.documents),
            ],
        ).fetchone()
    )


def _import_document(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    document: DescriptionDocumentInput,
    source_id: str,
    osm_source_id: str,
    run_id: str,
    embedding_version: str,
) -> Literal["updated", "unchanged", "unknown_place", "source_place_conflict"]:
    place_row = connection.execute(
        """
        SELECT p.id
        FROM places p
        JOIN place_source_records psr ON psr.place_id = p.id
        WHERE psr.source_id = %s AND psr.external_id = %s
          AND psr.deleted_at IS NULL AND p.deleted_at IS NULL
        """,
        [osm_source_id, document.place_osm_external_id],
    ).fetchone()
    if place_row is None:
        return "unknown_place"
    place_id = str(place_row["id"])
    existing_source_record = connection.execute(
        """
        SELECT id, place_id
        FROM place_source_records
        WHERE source_id = %s AND external_id = %s
        """,
        [source_id, document.source_external_id],
    ).fetchone()
    if existing_source_record is not None and str(existing_source_record["place_id"]) != place_id:
        return "source_place_conflict"
    payload = document.model_dump(mode="json")
    payload_checksum = _checksum(payload)
    source_record_id = _required_id(
        connection.execute(
            """
            INSERT INTO place_source_records (
                place_id, source_id, external_id, source_url, source_category, source_payload
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            ON CONFLICT (source_id, external_id) DO UPDATE SET
                source_url = EXCLUDED.source_url,
                source_category = EXCLUDED.source_category,
                source_payload = EXCLUDED.source_payload,
                last_seen_at = now(),
                deleted_at = NULL
            RETURNING id
            """,
            [
                place_id,
                source_id,
                document.source_external_id,
                document.source_url,
                f"poi_description:{document.content_kind}",
                json.dumps(payload),
            ],
        ).fetchone()
    )
    snapshot_id = _snapshot_id(
        connection,
        source_record_id=source_record_id,
        run_id=run_id,
        checksum=payload_checksum,
        payload=payload,
    )
    existing = connection.execute(
        """
        SELECT id, content_checksum
        FROM place_description_documents
        WHERE place_source_record_id = %s AND language_code = %s AND content_kind = %s
        """,
        [source_record_id, document.language_code, document.content_kind],
    ).fetchone()
    content_changed = existing is None or existing["content_checksum"] != _checksum(document.text)
    document_id = _required_id(
        connection.execute(
            """
            INSERT INTO place_description_documents (
                place_id, place_source_record_id, source_snapshot_id, language_code, content_kind,
                text_content, content_checksum, observed_at, valid_until
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (place_source_record_id, language_code, content_kind) DO UPDATE SET
                place_id = EXCLUDED.place_id,
                source_snapshot_id = EXCLUDED.source_snapshot_id,
                text_content = EXCLUDED.text_content,
                content_checksum = EXCLUDED.content_checksum,
                observed_at = EXCLUDED.observed_at,
                valid_until = EXCLUDED.valid_until,
                updated_at = now()
            RETURNING id
            """,
            [
                place_id,
                source_record_id,
                snapshot_id,
                document.language_code,
                document.content_kind,
                document.text,
                _checksum(document.text),
                document.observed_at,
                document.valid_until,
            ],
        ).fetchone()
    )
    if not content_changed:
        return "unchanged"
    connection.execute("DELETE FROM place_description_chunks WHERE document_id = %s", [document_id])
    for position, chunk in enumerate(split_description_text(document.text)):
        connection.execute(
            """
            INSERT INTO place_description_chunks (
                document_id, position, text_content, content_checksum, token_estimate,
                embedding, embedding_version
            ) VALUES (%s, %s, %s, %s, %s, %s::vector, %s)
            """,
            [
                document_id,
                position,
                chunk,
                _checksum(chunk),
                max(1, (len(chunk) + 3) // 4),
                vector_literal(deterministic_embedding([chunk])),
                embedding_version,
            ],
        )
    return "updated"


def _snapshot_id(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    source_record_id: str,
    run_id: str,
    checksum: str,
    payload: dict[str, Any],
) -> str:
    existing = connection.execute(
        """
        SELECT id FROM place_source_snapshots
        WHERE place_source_record_id = %s AND checksum = %s
        """,
        [source_record_id, checksum],
    ).fetchone()
    if existing is not None:
        return str(existing["id"])
    return _required_id(
        connection.execute(
            """
            INSERT INTO place_source_snapshots (
                place_source_record_id, import_run_id, checksum, payload
            ) VALUES (%s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            [source_record_id, run_id, checksum, json.dumps(payload)],
        ).fetchone()
    )


def _complete_import_run(
    connection: psycopg.Connection[dict[str, Any]],
    *,
    run_id: str,
    accepted: int,
    rejected: int,
    rejection_reasons: Counter[str],
    completed_at: datetime,
) -> None:
    connection.execute(
        """
        UPDATE import_runs
        SET status = 'completed', completed_at = %s, accepted_count = %s, merged_count = 0,
            rejected_count = %s, rejection_reasons = %s::jsonb,
            manifest = manifest || %s::jsonb
        WHERE id = %s
        """,
        [
            completed_at,
            accepted,
            rejected,
            json.dumps(dict(rejection_reasons)),
            json.dumps({"completed_at": completed_at.isoformat()}),
            run_id,
        ],
    )


def _is_expired(valid_until: datetime | None, *, now: datetime) -> bool:
    if valid_until is None:
        return False
    return valid_until <= now
