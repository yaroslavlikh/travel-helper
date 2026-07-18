from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.places.descriptions import (
    DescriptionManifest,
    normalize_description_text,
    split_description_text,
)


def manifest_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "destination": "istanbul",
        "source": {
            "slug": "licensed-guide",
            "name": "Licensed Istanbul Guide",
            "license": "Direct partner permission, 2026-07-18",
            "attribution": "© Licensed Istanbul Guide",
            "base_url": "https://guide.example/",
            "usage_policy": {
                "may_store_text": True,
                "may_embed_text": True,
                "may_display_excerpt": True,
                "requires_attribution": True,
                "reviewed_at": "2026-07-18T10:00:00+00:00",
                "review_note": "Partner agreement permits bounded RAG reuse and attribution.",
            },
        },
        "documents": [
            {
                "source_external_id": "aya-sophia-overview-ru",
                "source_url": "https://guide.example/aya-sophia",
                "place_osm_external_id": "way/12345",
                "language_code": "ru",
                "content_kind": "overview",
                "text": (
                    "Это проверенный пример описания конкретного места для импорта в каталог. "
                    "Он достаточно длинный, чтобы пройти границу минимальной длины, и содержит "
                    "только обычный текст без HTML или скрытых инструкций."
                ),
                "observed_at": "2026-07-18T10:00:00+00:00",
            }
        ],
    }


def test_description_manifest_requires_recorded_reuse_permissions() -> None:
    payload = manifest_payload()
    source = payload["source"]
    assert isinstance(source, dict)
    usage_policy = source["usage_policy"]
    assert isinstance(usage_policy, dict)
    usage_policy["may_embed_text"] = False

    with pytest.raises(ValidationError, match="permission to store, embed and display"):
        DescriptionManifest.model_validate(payload)


def test_description_manifest_rejects_duplicate_source_document_ids() -> None:
    payload = manifest_payload()
    documents = payload["documents"]
    assert isinstance(documents, list)
    documents.append(dict(documents[0]))

    with pytest.raises(ValidationError, match="source_external_id"):
        DescriptionManifest.model_validate(payload)


def test_description_manifest_requires_timezone_aware_freshness() -> None:
    payload = manifest_payload()
    documents = payload["documents"]
    assert isinstance(documents, list)
    document = documents[0]
    assert isinstance(document, dict)
    document["observed_at"] = "2026-07-18T10:00:00"

    with pytest.raises(ValidationError, match="include a timezone"):
        DescriptionManifest.model_validate(payload)


def test_description_chunking_is_bounded_and_lossless_after_normalization() -> None:
    text = " ".join(
        [
            "Первое предложение описывает исторический контекст конкретного места.",
            "Второе предложение добавляет полезную туристическую деталь без операционных обещаний.",
            "Третье предложение сохраняет текст достаточно длинным для валидного документа.",
            "Четвёртое предложение помогает проверить разбиение на короткие RAG-фрагменты.",
        ]
    )

    chunks = split_description_text(text, max_chars=110)

    assert len(chunks) > 1
    assert all(len(chunk) <= 110 for chunk in chunks)
    assert " ".join(chunks) == normalize_description_text(text).replace("\n\n", " ")


def test_description_manifest_accepts_future_expiry() -> None:
    payload = manifest_payload()
    documents = payload["documents"]
    assert isinstance(documents, list)
    document = documents[0]
    assert isinstance(document, dict)
    document["valid_until"] = datetime(2026, 8, 1, tzinfo=UTC).isoformat()

    manifest = DescriptionManifest.model_validate(payload)

    assert manifest.documents[0].valid_until == datetime(2026, 8, 1, tzinfo=UTC)
