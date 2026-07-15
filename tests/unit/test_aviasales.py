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
        departure_window_from=date(2026, 8, 15),
        departure_window_to=date(2026, 8, 16),
        adults=1,
    )

    url = build_aviasales_url(
        request,
        destination_iata="BUS",
    )

    assert url == "https://www.aviasales.ru/routes/mow/bus"


def test_confirmed_round_trip_dates_and_passengers_are_sent_to_aviasales() -> None:
    request = TravelRequest(
        raw_query="Точно лечу с 15 по 23 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 23),
        adults=1,
    )

    url = build_aviasales_url(
        request,
        destination_iata="bus",
        marker="partner.subid",
    )
    assert urlparse(url).path == "/search/"
    assert query_params(url) == {
        "origin_iata": ["MOW"],
        "destination_iata": ["BUS"],
        "depart_date": ["2026-08-15"],
        "return_date": ["2026-08-23"],
        "oneway": ["0"],
        "adults": ["1"],
        "children": ["0"],
        "infants": ["0"],
        "trip_class": ["0"],
        "marker": ["partner.subid"],
    }


def test_confirmed_one_way_trip_uses_exact_departure_date() -> None:
    request = TravelRequest(
        raw_query="Обратный билет не нужен",
        origin_city="Санкт-Петербург",
        date_from=date(2026, 9, 2),
        flight_one_way=True,
        adults=2,
    )

    url = build_aviasales_url(
        request,
        destination_iata="AYT",
    )

    assert query_params(url) == {
        "origin_iata": ["LED"],
        "destination_iata": ["AYT"],
        "depart_date": ["2026-09-02"],
        "oneway": ["1"],
        "adults": ["2"],
        "children": ["0"],
        "infants": ["0"],
        "trip_class": ["0"],
    }


def test_moscow_abbreviation_still_keeps_the_route() -> None:
    request = TravelRequest(raw_query="Вылет из МСК", origin_city="МСК", adults=1)

    url = build_aviasales_url(request, destination_iata="AER")

    assert url == "https://www.aviasales.ru/routes/mow/aer"


def test_unknown_origin_never_falls_back_to_moscow_route() -> None:
    request = TravelRequest(raw_query="Из Тулы", origin_city="Тула", adults=1)

    url = build_aviasales_url(request, destination_iata="AER")

    assert url == "https://www.aviasales.ru/"


def test_family_request_sends_exact_dates_and_all_passengers() -> None:
    request = TravelRequest(
        raw_query="С ребёнком с 15 по 23 августа",
        origin_city="Москва",
        date_from=date(2026, 8, 15),
        date_to=date(2026, 8, 23),
        adults=2,
        children=1,
    )

    url = build_aviasales_url(
        request,
        destination_iata="AER",
    )

    assert query_params(url)["adults"] == ["2"]
    assert query_params(url)["children"] == ["1"]
    assert query_params(url)["return_date"] == ["2026-08-23"]


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
    assert flight_links[0].url.startswith("https://www.aviasales.ru/routes/mow/")
    assert flight_links[0].title == "Выбрать даты"
