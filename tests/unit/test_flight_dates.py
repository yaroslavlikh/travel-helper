from datetime import date

from app.domain.models import TravelRequest
from app.services.flight_dates import build_flight_date_options, timing_is_ready

TODAY = date(2026, 7, 15)


def test_exact_dates_return_one_exact_option_without_duration_input() -> None:
    request = TravelRequest(
        raw_query="С 10 по 17 августа",
        date_from=date(2026, 8, 10),
        date_to=date(2026, 8, 17),
    )

    options = build_flight_date_options(request, today=TODAY)

    assert timing_is_ready(request, today=TODAY) is True
    assert [option.model_dump(mode="json") for option in options] == [
        {
            "departure_date": "2026-08-10",
            "return_date": "2026-08-17",
            "duration_nights": 7,
            "date_mode": "exact",
        }
    ]


def test_month_and_duration_range_create_three_visible_presets() -> None:
    request = TravelRequest(
        raw_query="В августе на 7–10 ночей",
        month=8,
        duration_nights_min=7,
        duration_nights_max=10,
    )

    options = build_flight_date_options(request, today=TODAY)

    assert timing_is_ready(request, today=TODAY) is True
    assert [
        (option.departure_date, option.return_date, option.duration_nights) for option in options
    ] == [
        (date(2026, 8, 1), date(2026, 8, 8), 7),
        (date(2026, 8, 11), date(2026, 8, 20), 9),
        (date(2026, 8, 21), date(2026, 8, 31), 10),
    ]
    assert all(option.date_mode == "derived" for option in options)


def test_one_departure_date_builds_return_options_from_duration_range() -> None:
    request = TravelRequest(
        raw_query="После 10 августа на 7–10 ночей",
        date_from=date(2026, 8, 10),
        duration_nights_min=7,
        duration_nights_max=10,
    )

    options = build_flight_date_options(request, today=TODAY)

    assert [option.return_date for option in options] == [
        date(2026, 8, 17),
        date(2026, 8, 19),
        date(2026, 8, 20),
    ]


def test_past_month_resolves_to_its_next_occurrence() -> None:
    request = TravelRequest(
        raw_query="В июне на неделю",
        month=6,
        duration_nights_min=7,
    )

    [option] = build_flight_date_options(request, today=TODAY)

    assert option.departure_date.year == 2027
    assert option.return_date <= date(2027, 6, 30)


def test_current_month_never_builds_a_past_departure() -> None:
    request = TravelRequest(
        raw_query="В июле на неделю",
        month=7,
        duration_nights_min=7,
    )

    [option] = build_flight_date_options(request, today=TODAY)

    assert option.departure_date >= TODAY


def test_current_month_rolls_to_next_year_when_no_duration_fits() -> None:
    request = TravelRequest(
        raw_query="В июле на неделю",
        month=7,
        duration_nights_min=7,
    )

    [option] = build_flight_date_options(request, today=date(2026, 7, 30))

    assert option.departure_date.year == 2027
    assert option.return_date <= date(2027, 7, 30)


def test_leap_february_and_too_long_duration_are_handled() -> None:
    leap_request = TravelRequest(
        raw_query="В феврале на неделю",
        month=2,
        duration_nights_min=7,
    )
    too_long = TravelRequest(
        raw_query="В феврале на 30 ночей",
        month=2,
        duration_nights_min=30,
    )

    [leap_option] = build_flight_date_options(leap_request, today=date(2023, 3, 1))

    assert leap_option.return_date <= date(2024, 2, 29)
    assert build_flight_date_options(too_long, today=date(2023, 3, 1)) == []


def test_invalid_duration_range_is_not_ready() -> None:
    request = TravelRequest(
        raw_query="В августе на 10–7 ночей",
        month=8,
        duration_nights_min=10,
        duration_nights_max=7,
    )

    assert timing_is_ready(request, today=TODAY) is False
    assert build_flight_date_options(request, today=TODAY) == []
