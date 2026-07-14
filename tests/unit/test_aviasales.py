from datetime import date
from urllib.parse import parse_qs, urlparse

from app.domain.models import TravelRequest
from app.services.aviasales import add_aviasales_links, build_aviasales_url
from app.services.scoring import rank_demo_candidates


def query_params(url: str) -> dict[str, list[str]]:
    return parse_qs(urlparse(url).query)


def test_flexible_planning_window_is_not_sent_as_round_trip_dates() -> None:
    request = TravelRequest(
        raw_query="Можно улететь 15 или 16 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 16),
        adults=2,
        children=1,
        infants=1,
    )

    params = query_params(
        build_aviasales_url(
            request,
            destination_iata="BUS",
            today=date(2026, 7, 15),
        )
    )

    assert params["origin_iata"] == ["MOW"]
    assert params["destination_iata"] == ["BUS"]
    assert params["adults"] == ["2"]
    assert params["children"] == ["1"]
    assert params["infants"] == ["1"]
    assert "depart_date" not in params
    assert "return_date" not in params
    assert "oneway" not in params


def test_confirmed_round_trip_dates_follow_aviasales_contract() -> None:
    request = TravelRequest(
        raw_query="Точно лечу с 15 по 23 августа",
        origin_city="Москва",
        flight_departure_date=date(2026, 8, 15),
        flight_return_date=date(2026, 8, 23),
        adults=1,
    )

    url = build_aviasales_url(
        request,
        destination_iata="bus",
        marker="partner.subid",
        today=date(2026, 7, 15),
    )
    params = query_params(url)

    assert url.startswith("https://www.aviasales.ru/search?")
    assert params["depart_date"] == ["2026-08-15"]
    assert params["return_date"] == ["2026-08-23"]
    assert params["oneway"] == ["0"]
    assert params["marker"] == ["partner.subid"]


def test_confirmed_one_way_trip_omits_return_date() -> None:
    request = TravelRequest(
        raw_query="Обратный билет не нужен",
        origin_city="Санкт-Петербург",
        flight_departure_date=date(2026, 9, 2),
        flight_one_way=True,
        adults=1,
    )

    params = query_params(
        build_aviasales_url(
            request,
            destination_iata="AYT",
            today=date(2026, 7, 15),
        )
    )

    assert params["origin_iata"] == ["LED"]
    assert params["depart_date"] == ["2026-09-02"]
    assert params["oneway"] == ["1"]
    assert "return_date" not in params


def test_unknown_origin_never_falls_back_to_moscow_route() -> None:
    request = TravelRequest(raw_query="Из Тулы", origin_city="Тула", adults=1)

    params = query_params(build_aviasales_url(request, destination_iata="AER"))

    assert "origin_iata" not in params
    assert "destination_iata" not in params


def test_recommendations_receive_one_backend_generated_flight_link() -> None:
    request = TravelRequest(
        raw_query="Из Москвы в августе",
        origin_city="Москва",
        month=8,
        adults=1,
        budget_total_rub=200_000,
        destination_scope="any",
    )

    recommendations = add_aviasales_links(rank_demo_candidates(request, limit=1), request)
    links = recommendations[0].candidate.external_links
    flight_links = [link for link in links if link.category == "flight"]

    assert len(flight_links) == 1
    assert flight_links[0].provider == "aviasales"
    assert "destination_iata=" in flight_links[0].url
