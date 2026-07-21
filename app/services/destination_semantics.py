"""Normalize user-facing destination preferences for deterministic filtering and scoring."""

from __future__ import annotations

from app.domain.models import DestinationCandidate, TravelRequest

REGION_COUNTRIES = {
    "asia": {"Вьетнам", "Индонезия", "Малайзия", "Таиланд"},
    "europe": {"Испания", "Греция", "Италия", "Черногория"},
    "middle_east": {"ОАЭ", "Египет", "Турция"},
    "russia": {"Россия"},
}

REGION_ALIASES = {
    "asia": ("ази", "asia"),
    "europe": ("европ", "europe"),
    "middle_east": ("ближн", "middle east"),
    "russia": ("росси", "внутренн", "domestic"),
}

PREFERENCE_TAG_ALIASES = {
    "spicy_food": ("остр", "spicy"),
    "food": ("ед", "кухн", "гастроном", "food"),
    "nightlife": ("ночн", "тусов", "активност", "развлечен", "движ", "nightlife"),
    "beach": ("пляж", "beach"),
    "nature": ("природ", "nature"),
    "family": ("семейн", "с детьми", "family"),
    "diving": ("дайв", "сноркл", "diving"),
    "city": ("инфраструктур", "городск", "city"),
}

AVOIDED_TAG_ALIASES = {"sea": ("море", "пляж", "sea", "beach")}


def requested_regions(request: TravelRequest) -> set[str]:
    """Return explicit geographic regions embedded in the current request lists."""

    values = [*request.preferences, *request.trip_style, *request.priorities]
    text = " ".join(values).casefold()
    return {
        region
        for region, aliases in REGION_ALIASES.items()
        if any(alias in text for alias in aliases)
    }


def matches_requested_regions(candidate: DestinationCandidate, request: TravelRequest) -> bool:
    """Treat an explicit region request as a hard geographic constraint."""

    regions = requested_regions(request)
    if not regions:
        return True
    allowed_countries = set().union(*(REGION_COUNTRIES[region] for region in regions))
    return candidate.country in allowed_countries


def matches_explicit_avoid(candidate: DestinationCandidate, request: TravelRequest) -> bool:
    """Match inflected Russian country/city exclusions without asking the model again."""

    avoid_text = " ".join(request.avoid).casefold()
    if not avoid_text:
        return False
    values = (candidate.country, candidate.city_or_region)
    return any(_russian_stem(value) in avoid_text for value in values)


def normalized_preference_tags(request: TravelRequest) -> set[str]:
    """Map natural-language preferences to the controlled destination tag vocabulary."""

    values = [*request.preferences, *request.trip_style, *request.priorities]
    normalized: set[str] = set()
    for value in values:
        text = value.casefold()
        for tag, aliases in PREFERENCE_TAG_ALIASES.items():
            if any(alias in text for alias in aliases):
                normalized.add(tag)
    return normalized


def normalized_avoided_tags(request: TravelRequest) -> set[str]:
    """Map explicit non-geographic dislikes into candidate tags for scoring."""

    text = " ".join(request.avoid).casefold()
    return {
        tag
        for tag, aliases in AVOIDED_TAG_ALIASES.items()
        if any(alias in text for alias in aliases)
    }


def _russian_stem(value: str) -> str:
    normalized = value.strip().casefold()
    if len(normalized) > 5 and normalized.endswith(("ия", "ья")):
        return normalized[:-2]
    if len(normalized) > 4 and normalized.endswith(("а", "я", "ы", "и", "ь")):
        return normalized[:-1]
    return normalized
