from app.domain.models import TravelRequest
from app.services.filtering import hard_filter_reasons
from app.services.fixtures import load_demo_candidates
from app.services.scoring import load_scoring_weights, rank_demo_candidates, score_candidate


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


def test_scoring_is_deterministic_and_retains_sources() -> None:
    request = _sample_request()
    batumi = next(item for item in load_demo_candidates() if item.destination_id == "batumi")

    assert score_candidate(batumi, request) == score_candidate(batumi, request)
    ranked = rank_demo_candidates(request)
    assert ranked == sorted(ranked, key=lambda item: item.total_score, reverse=True)
    assert all(item.candidate.sources for item in ranked)


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
