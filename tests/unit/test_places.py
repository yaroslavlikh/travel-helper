import json
from pathlib import Path

from app.places.importer import normalize_osm_payload, overpass_query
from app.places.semantics import deterministic_embedding, inferred_categories, normalize_text


def test_normalizes_only_named_mapped_places_with_coordinates() -> None:
    records, rejected = normalize_osm_payload(
        {
            "elements": [
                {
                    "type": "node",
                    "id": 1,
                    "lat": 41.0086,
                    "lon": 28.9802,
                    "tags": {"name": "Aya Sofya", "tourism": "museum"},
                },
                {
                    "type": "node",
                    "id": 2,
                    "lat": 41.0,
                    "lon": 29.0,
                    "tags": {"name": "Not a tourist place", "shop": "bakery"},
                },
                {"type": "node", "id": 3, "tags": {"tourism": "museum"}},
            ]
        }
    )

    assert [(item.external_id, item.category) for item in records] == [("node/1", "museum")]
    assert rejected == {"unmapped_category": 1, "missing_name": 1}


def test_local_embedding_is_deterministic_and_normalized() -> None:
    first = deterministic_embedding(["Istanbul museum"])
    second = deterministic_embedding(["Istanbul museum"])

    assert first == second
    assert len(first) == 64
    assert normalize_text("  Aya-Sofya! ") == "aya-sofya"


def test_istanbul_eval_set_has_thirty_searchable_cases() -> None:
    path = Path("data/evals/istanbul_places_queries.json")
    cases = json.loads(path.read_text(encoding="utf-8"))

    assert len(cases) == 30
    assert all(case["query"] and case["expected_categories"] for case in cases)


def test_overpass_query_applies_istanbul_bbox_to_each_selector() -> None:
    query = overpass_query()

    assert query.count("(40.8,28.55,41.35,29.45)") == 5
    assert ")(40.8,28.55,41.35,29.45)" not in query


def test_infers_explainable_category_hints_from_russian_place_intent() -> None:
    assert inferred_categories("романтичный закат на Босфоре") == ["viewpoint"]
    assert inferred_categories("местный рынок и сувениры") == ["market"]
