import pytest

from app.domain.models import TravelRequest
from app.services.extraction import extract_travel_request
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


def test_strict_budget_uses_safe_total_not_the_lowest_estimate() -> None:
    candidate = next(item for item in load_demo_candidates() if item.destination_id == "antalya")
    request = TravelRequest(
        raw_query="Строго до 150 тысяч",
        budget_total_rub=150_000,
        budget_strict=True,
    )

    scored = score_candidate(candidate, request)

    assert "strict_budget_exceeded" in scored.rejected_reasons
    assert scored.hard_checks["strict_budget"] == "FAIL"
    assert scored.state == "EXCLUDED"


@pytest.mark.parametrize(
    ("minimum", "maximum", "expected"),
    [
        (160_000, 180_000, "FAIL"),
        (100_000, 160_000, "FAIL"),
        (100_000, 150_000, "PASS"),
        (None, 150_000, "PASS"),
        (100_000, None, "UNKNOWN"),
    ],
)
def test_strict_budget_hard_check_is_tristate(
    minimum: int | None, maximum: int | None, expected: str
) -> None:
    candidate = next(
        item for item in load_demo_candidates() if item.destination_id == "antalya"
    ).model_copy(
        update={"estimated_total_cost_rub_min": minimum, "estimated_total_cost_rub_max": maximum}
    )

    scored = score_candidate(
        candidate,
        TravelRequest(
            raw_query="Строго до 150 тысяч", budget_total_rub=150_000, budget_strict=True
        ),
    )

    assert scored.hard_checks["strict_budget"] == expected


@pytest.mark.parametrize(
    ("visa_willingness", "visa_complexity", "expected"),
    [
        ("no_visa", "none", "PASS"),
        ("no_visa", "evisa", "FAIL"),
        ("no_visa", "unknown", "UNKNOWN"),
        ("evisa_ok", "none", "PASS"),
        ("evisa_ok", "evisa", "PASS"),
        ("evisa_ok", "visa", "FAIL"),
        ("evisa_ok", "unknown", "UNKNOWN"),
        ("visa_ok", "visa", "PASS"),
        ("any", "unknown", "NOT_APPLICABLE"),
    ],
)
def test_visa_hard_check_semantics(
    visa_willingness: str, visa_complexity: str, expected: str
) -> None:
    candidate = next(
        item for item in load_demo_candidates() if item.destination_id == "antalya"
    ).model_copy(update={"visa_complexity": visa_complexity})

    scored = score_candidate(
        candidate,
        TravelRequest(raw_query="Виза", visa_willingness=visa_willingness),  # type: ignore[arg-type]
    )

    assert scored.hard_checks["visa"] == expected


@pytest.mark.parametrize(
    ("field", "update", "travel_request", "check"),
    [
        (
            "flight",
            {"flight_duration_hours": None},
            TravelRequest(raw_query="Не дольше 5 часов", max_flight_duration_hours=5),
            "max_flight_duration",
        ),
        (
            "temperature",
            {"expected_temperature_c": None},
            TravelRequest(raw_query="Не жарче 28", preferred_max_temperature_c=28),
            "temperature_limit",
        ),
    ],
)
def test_missing_hard_evidence_is_conditional(
    field: str, update: dict[str, object], travel_request: TravelRequest, check: str
) -> None:
    candidate = next(
        item for item in load_demo_candidates() if item.destination_id == "antalya"
    ).model_copy(update=update)

    scored = score_candidate(candidate, travel_request)

    assert field
    assert scored.hard_checks[check] == "UNKNOWN"
    assert scored.state == "CONDITIONAL"
    assert "Соответствует подтверждённым условиям." not in scored.pros


@pytest.mark.parametrize(
    ("field", "update", "travel_request", "check"),
    [
        (
            "flight",
            {"flight_duration_hours": 6},
            TravelRequest(raw_query="Не дольше 5 часов", max_flight_duration_hours=5),
            "max_flight_duration",
        ),
        (
            "temperature",
            {"expected_temperature_c": 29},
            TravelRequest(raw_query="Не жарче 28", preferred_max_temperature_c=28),
            "temperature_limit",
        ),
    ],
)
def test_known_hard_evidence_above_limit_fails(
    field: str, update: dict[str, object], travel_request: TravelRequest, check: str
) -> None:
    candidate = next(
        item for item in load_demo_candidates() if item.destination_id == "antalya"
    ).model_copy(update=update)

    scored = score_candidate(candidate, travel_request)

    assert field
    assert scored.hard_checks[check] == "FAIL"
    assert scored.state == "EXCLUDED"


def test_absent_user_constraints_create_no_unknown_hard_checks() -> None:
    candidate = next(item for item in load_demo_candidates() if item.destination_id == "antalya")

    assert score_candidate(candidate, TravelRequest(raw_query="Хочу отдохнуть")).hard_checks == {}


def test_missing_dimension_keeps_its_weight_and_conservative_prior() -> None:
    candidate = next(
        item for item in load_demo_candidates() if item.destination_id == "antalya"
    ).model_copy(
        update={"estimated_total_cost_rub_min": None, "estimated_total_cost_rub_max": None}
    )
    scored = score_candidate(
        candidate, TravelRequest(raw_query="Нужен отпуск", budget_total_rub=150_000)
    )

    assert scored.score_breakdown["budget"] == 8.4
    assert scored.uncertainty_penalty > 0


def test_fallback_is_labeled_and_never_claims_passed_hard_filters() -> None:
    request = TravelRequest(
        raw_query="Азия строго до 150 тысяч",
        budget_total_rub=150_000,
        budget_strict=True,
        preferences=["Азия"],
    )

    ranked = rank_demo_candidates(request)

    assert ranked
    assert all(item.state == "FALLBACK" for item in ranked)
    assert all(not item.passed_hard_filters for item in ranked)
    assert all(item.rank_before_diversity and item.rank_after_diversity for item in ranked)
    assert all(STRICT_BUDGET_FALLBACK in item.cons for item in ranked)


def test_unknown_visa_does_not_pass_a_no_visa_hard_requirement() -> None:
    candidate = next(item for item in load_demo_candidates() if item.destination_id == "kohsamui")

    scored = score_candidate(
        candidate, TravelRequest(raw_query="Только без визы", visa_willingness="no_visa")
    )

    assert scored.hard_checks["visa"] == "UNKNOWN"
    assert scored.state == "EXCLUDED"
    assert not scored.passed_hard_filters


@pytest.mark.parametrize(
    ("travel_request", "better_id", "worse_id"),
    [
        (TravelRequest(raw_query="Не хочу море", avoid=["море"]), "kualalumpur", "phuket"),
        (
            TravelRequest(raw_query="Нужна инфраструктура", preferences=["инфраструктура"]),
            "kualalumpur",
            "phuket",
        ),
        (
            TravelRequest(raw_query="Приоритет — инфраструктура", priorities=["инфраструктура"]),
            "kualalumpur",
            "phuket",
        ),
    ],
)
def test_experience_fit_normalizes_preferences_avoids_and_priorities(
    travel_request: TravelRequest, better_id: str, worse_id: str
) -> None:
    candidates = load_demo_candidates()
    better = next(item for item in candidates if item.destination_id == better_id)
    worse = next(item for item in candidates if item.destination_id == worse_id)

    assert (
        score_candidate(better, travel_request).score_breakdown["experience"]
        > score_candidate(worse, travel_request).score_breakdown["experience"]
    )


def test_affiliate_navigation_links_do_not_change_relevance_score() -> None:
    candidate = next(item for item in load_demo_candidates() if item.destination_id == "antalya")
    request = TravelRequest(raw_query="Море", sea_required=True)

    assert (
        score_candidate(candidate, request).final_score
        == score_candidate(candidate.model_copy(update={"external_links": []}), request).final_score
    )


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


@pytest.mark.parametrize("avoid", [["постсоветские страны"], ["СНГ"], ["бывший СССР"]])
def test_post_soviet_country_group_excludes_georgia(avoid: list[str]) -> None:
    candidates = load_demo_candidates()
    request = TravelRequest(raw_query="Не хочу в постсоветские страны", avoid=avoid)
    batumi = next(item for item in candidates if item.destination_id == "batumi")
    antalya = next(item for item in candidates if item.destination_id == "antalya")

    assert hard_filter_reasons(batumi, request) == ["explicitly_avoided"]
    assert hard_filter_reasons(antalya, request) == []


def test_post_soviet_exclusion_survives_extraction_and_shortlist_ranking() -> None:
    request = extract_travel_request(
        "Из Москвы за границу в августе, не хочу в постсоветские страны"
    )

    ranked = rank_demo_candidates(request)

    assert ranked
    assert all(item.candidate.country != "Грузия" for item in ranked)


@pytest.mark.parametrize(
    ("region", "allowed_countries"),
    [
        ("Азия", {"Таиланд", "Малайзия", "Вьетнам", "Индонезия"}),
        ("Европа", {"Испания", "Греция", "Италия", "Черногория"}),
        ("Ближний Восток", {"ОАЭ", "Египет", "Турция"}),
        ("Россия", {"Россия"}),
    ],
)
def test_controlled_regions_are_hard_filters(region: str, allowed_countries: set[str]) -> None:
    ranked = rank_demo_candidates(TravelRequest(raw_query=f"Хочу {region}", preferences=[region]))

    assert ranked
    assert all(item.candidate.country in allowed_countries for item in ranked)


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


def test_fallback_never_relaxes_unknown_visa_or_other_hard_constraints() -> None:
    ranked = rank_demo_candidates(
        TravelRequest(
            raw_query="Азия, только без визы, строго до 150к",
            budget_total_rub=150_000,
            budget_strict=True,
            preferences=["Азия"],
            visa_willingness="no_visa",
        )
    )

    assert all(item.candidate.visa_complexity == "none" for item in ranked)


def test_ordering_and_diversity_are_deterministic_and_bounded() -> None:
    request = TravelRequest(raw_query="Море", destination_scope="international", sea_required=True)

    first = rank_demo_candidates(request)
    second = rank_demo_candidates(request)

    assert [item.candidate.destination_id for item in first] == [
        item.candidate.destination_id for item in second
    ]
    assert [item.rank_after_diversity for item in first] == [
        item.rank_after_diversity for item in second
    ]
    assert first[0].rank_before_diversity == 1
    assert all(item.final_score >= first[0].final_score - 12 for item in first)
    assert all(
        sum(other.candidate.country == item.candidate.country for other in first) <= 2
        for item in first
    )


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
