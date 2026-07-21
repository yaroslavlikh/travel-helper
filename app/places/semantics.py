"""Deterministic normalization and local embedding used by the first city slice."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable

EMBEDDING_DIMENSIONS = 64

OSM_CATEGORY_MAP = {
    "museum": "museum",
    "gallery": "gallery",
    "attraction": "sight",
    "viewpoint": "viewpoint",
    "zoo": "family",
    "theme_park": "family",
    "park": "park",
    "garden": "park",
    "beach": "beach",
    "marketplace": "market",
    "nightclub": "nightlife",
    "monument": "historic",
    "memorial": "historic",
    "castle": "historic",
    "archaeological_site": "historic",
}

CATEGORY_TAGS = {
    "museum": {"indoor", "rainy_day", "culture"},
    "gallery": {"indoor", "rainy_day", "culture"},
    "sight": {"architecture", "instagrammable", "outdoor"},
    "viewpoint": {"outdoor", "instagrammable", "romantic"},
    "family": {"family_friendly"},
    "park": {"outdoor", "budget_friendly", "family_friendly"},
    "beach": {"outdoor", "budget_friendly"},
    "market": {"local_experience", "budget_friendly", "indoor"},
    "nightlife": {"nightlife", "indoor"},
    "historic": {"architecture", "culture", "instagrammable"},
}

QUERY_CATEGORY_HINTS = {
    "museum": ("музе",),
    "gallery": ("галере", "искусств", "современн"),
    "historic": ("истор", "древност", "мемориал", "дворц", "памятник", "архитект"),
    "sight": ("достопримечатель", "впервые"),
    "viewpoint": ("видов", "смотров", "босфор", "закат", "романтич", "вода"),
    "park": ("парк", "сад", "прогул", "дет", "семейн"),
    "beach": ("пляж", "море", "набережн"),
    "market": ("рынок", "сувенир", "локальн", "нетурист"),
    "nightlife": ("ночн", "клуб", "вечер"),
    "family": ("дет", "семейн"),
}

AREA_HINTS = {
    "султанахмет": (41.0054, 28.9768, 1_500),
    "галат": (41.0261, 28.9786, 1_800),
    "карак": (41.0261, 28.9786, 1_800),
    "босфор": (41.0422, 29.0066, 2_500),
    "бешикташ": (41.0422, 29.0066, 2_500),
}


def normalize_text(value: str) -> str:
    """Lowercase a name for conservative equality checks across imports."""

    return " ".join(re.findall(r"[\wÀ-ÿ-]+", value.casefold(), flags=re.UNICODE))


def category_from_osm(tags: dict[str, str]) -> str | None:
    """Map only tourist-relevant OSM classes into the internal taxonomy."""

    for key in ("tourism", "historic", "leisure", "natural", "amenity"):
        value = tags.get(key)
        if value in OSM_CATEGORY_MAP:
            return OSM_CATEGORY_MAP[value]
    return None


def tags_for_category(category: str) -> set[str]:
    return set(CATEGORY_TAGS.get(category, set()))


def inferred_categories(query: str) -> list[str]:
    """Infer a small, explainable category boost from common Russian place intents."""

    normalized = normalize_text(query)
    return [
        category
        for category, hints in QUERY_CATEGORY_HINTS.items()
        if any(hint in normalized for hint in hints)
    ]


def inferred_area(query: str) -> tuple[float, float, int] | None:
    """Recognize only explicitly maintained Istanbul area hints for a transparent geo baseline."""

    normalized = normalize_text(query)
    return next((area for hint, area in AREA_HINTS.items() if hint in normalized), None)


def deterministic_embedding(parts: Iterable[str]) -> list[float]:
    """Create a stable local feature vector without sending text to an embedding API."""

    vector = [0.0] * EMBEDDING_DIMENSIONS
    for token in normalize_text(" ".join(parts)).split():
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % EMBEDDING_DIMENSIONS
        vector[index] += 1.0 if digest[2] % 2 else -1.0
    magnitude = sum(value * value for value in vector) ** 0.5
    return [round(value / magnitude, 8) if magnitude else 0.0 for value in vector]


def vector_literal(vector: list[float]) -> str:
    """Return pgvector's explicit textual literal format."""

    return "[" + ",".join(f"{value:.8f}" for value in vector) + "]"
