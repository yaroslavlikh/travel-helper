from app.domain.models import TravelRequest
from app.services.filtering import hard_filter_reasons
from app.services.fixtures import load_demo_candidates
from app.services.scoring import (
    STRICT_BUDGET_FALLBACK,
    load_scoring_weights,
    rank_demo_candidates,
    score_candidate,
)


def _sample_request() -> TravelRequest:
    return TravelRequest(
        raw_query="Из Москвы в августе на море",
        origin_city="Москва",
        month=8,
        adults=1,
        budget_total_rub=150_000,
        budget_strict=True,
        destination_scope="international",
        sea_required=True,
        heat_tolerance="low",
    )


def test_scoring_weights_sum_to_one_hundred() -> None:
    assert sum(load_scoring_weights().values()) == 100


def test_hard_filter_returns_machine_readable_reason() -> None:
    sochi = next(item for item in load_demo_candidates() if item.destination_id == "sochi")

    assert "destination_scope_mismatch" in hard_filter_reasons(sochi, _sample_request())


def test_region_and_country_exclusions_are_hard_filters() -> None:
    candidates = load_demo_candidates()
    request = TravelRequest(
        raw_query="Хочу Азию, не хочу Грузию",
        preferences=["Азия"],
        avoid=["Грузия"],
    )
    batumi = next(item for item in candidates if item.destination_id == "batumi")
    langkawi = next(item for item in candidates if item.destination_id == "langkawi")

    assert hard_filter_reasons(batumi, request) == [
        "preferred_region_mismatch",
        "explicitly_avoided",
    ]
    assert hard_filter_reasons(langkawi, request) == []


def test_scoring_is_deterministic_and_retains_sources() -> None:
    request = _sample_request()
    batumi = next(item for item in load_demo_candidates() if item.destination_id == "batumi")

    assert score_candidate(batumi, request) == score_candidate(batumi, request)
    ranked = rank_demo_candidates(request)
    assert ranked == sorted(ranked, key=lambda item: item.total_score, reverse=True)
    assert all(item.candidate.sources for item in ranked)


def test_asian_spicy_food_request_surfaces_malaysia_and_excludes_georgia() -> None:
    request = TravelRequest(
        raw_query="Хочу поесть острую еду за 150к, хочу Азию, не хочу Грузию",
        origin_city="Москва",
        adults=1,
        budget_total_rub=150_000,
        destination_scope="international",
        preferences=["острая еда", "Азия"],
        avoid=["Грузия"],
    )

    ranked = rank_demo_candidates(request)

    assert ranked
    assert all(
        item.candidate.country in {"Таиланд", "Малайзия", "Вьетнам", "Индонезия"} for item in ranked
    )
    assert any(item.candidate.country == "Малайзия" for item in ranked)
    assert all(item.candidate.country != "Грузия" for item in ranked)


def test_strict_budget_only_fallback_keeps_matching_destinations_visible() -> None:
    request = TravelRequest(
        raw_query="Хочу в Азию за 150к",
        origin_city="Москва",
        adults=1,
        budget_total_rub=150_000,
        budget_strict=True,
        destination_scope="international",
        preferences=["Азия"],
    )

    ranked = rank_demo_candidates(request)

    assert ranked
    assert all(
        item.candidate.country in {"Таиланд", "Малайзия", "Вьетнам", "Индонезия"} for item in ranked
    )
    assert all(STRICT_BUDGET_FALLBACK in item.assumptions for item in ranked)
    assert all(not item.passed_hard_filters for item in ranked)


def test_no_sea_and_infrastructure_rank_a_city_above_beach_resorts() -> None:
    request = TravelRequest(
        raw_query="Азия, инфраструктура и активности, не хочу море",
        destination_scope="international",
        preferences=["Азия", "инфраструктура", "активности"],
        avoid=["море"],
    )
    candidates = load_demo_candidates()
    kuala_lumpur = next(item for item in candidates if item.destination_id == "kualalumpur")
    phuket = next(item for item in candidates if item.destination_id == "phuket")

    assert (
        score_candidate(kuala_lumpur, request).total_score
        > score_candidate(phuket, request).total_score
    )


def test_demo_candidates_include_credited_places_and_navigation_links() -> None:
    candidates = load_demo_candidates()

    assert candidates
    for candidate in candidates:
        assert candidate.image is not None
        assert "commons.wikimedia.org" in candidate.image.source_url
        assert len(candidate.highlights) >= 2
        assert all(
            place.url.startswith("https://www.google.com/maps/") for place in candidate.highlights
        )
        assert candidate.stay_areas
        assert {link.category for link in candidate.external_links} == {
            "activity",
            "package_tour",
            "stay",
        }


def test_demo_bank_covers_major_tourist_countries_without_duplicate_routes() -> None:
    candidates = load_demo_candidates()
    destination_ids = [candidate.destination_id for candidate in candidates]
    route_keys = [
        (candidate.country, candidate.city_or_region, candidate.nearest_airport)
        for candidate in candidates
    ]

    assert len(candidates) >= 26
    assert len(destination_ids) == len(set(destination_ids))
    assert len(route_keys) == len(set(route_keys))
    assert {
        "Таиланд",
        "Малайзия",
        "Испания",
        "Греция",
        "Индонезия",
        "Вьетнам",
        "ОАЭ",
        "Турция",
        "Италия",
    }.issubset({candidate.country for candidate in candidates})
