"""Deterministic temporal readiness and concrete flight-search date options."""

from __future__ import annotations

import calendar
from datetime import date, timedelta

from app.domain.models import FlightDateOption, TravelRequest

MAX_FLIGHT_SEARCH_HORIZON_DAYS = 365


def exact_trip_dates_are_valid(request: TravelRequest, *, today: date | None = None) -> bool:
    """Return whether the request has a chronological, provider-safe exact date pair."""

    current_date = today or date.today()
    return bool(
        request.date_from
        and request.date_to
        and request.date_from >= current_date
        and request.date_to > request.date_from
        and request.date_to <= current_date + timedelta(days=MAX_FLIGHT_SEARCH_HORIZON_DAYS)
    )


def duration_range_is_valid(request: TravelRequest) -> bool:
    """A minimum duration is enough; an optional maximum must not contradict it."""

    if request.duration_nights_min is None:
        return False
    return bool(
        request.duration_nights_max is None
        or request.duration_nights_max >= request.duration_nights_min
    )


def timing_is_ready(request: TravelRequest, *, today: date | None = None) -> bool:
    """Require exact dates or a future departure anchor plus an approximate duration."""

    current_date = today or date.today()
    if exact_trip_dates_are_valid(request, today=current_date):
        return True
    has_future_departure = bool(
        request.date_from
        and current_date
        <= request.date_from
        <= current_date + timedelta(days=MAX_FLIGHT_SEARCH_HORIZON_DAYS)
    )
    return bool(
        (has_future_departure or request.month is not None) and duration_range_is_valid(request)
    )


def _duration_choices(request: TravelRequest) -> list[int]:
    minimum = request.duration_nights_min
    if minimum is None:
        return []
    maximum = request.duration_nights_max or minimum
    if maximum < minimum:
        return []
    midpoint = (minimum + maximum + 1) // 2
    return list(dict.fromkeys((minimum, midpoint, maximum)))


def _next_month_bounds(month: int, current_date: date) -> tuple[date, date]:
    year = current_date.year + int(month < current_date.month)
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    if month == current_date.month:
        first = max(first, current_date)
    return first, last


def _position_choices(count: int) -> tuple[float, ...]:
    if count <= 1:
        return (0.5,)
    if count == 2:
        return (0.0, 1.0)
    return (0.0, 0.5, 1.0)


def _month_option(
    *,
    earliest: date,
    month_end: date,
    duration_nights: int,
    position: float,
) -> FlightDateOption | None:
    latest_departure = month_end - timedelta(days=duration_nights)
    if latest_departure < earliest:
        return None
    available_days = (latest_departure - earliest).days
    departure = earliest + timedelta(days=round(available_days * position))
    return FlightDateOption(
        departure_date=departure,
        return_date=departure + timedelta(days=duration_nights),
        duration_nights=duration_nights,
        date_mode="derived",
    )


def build_flight_date_options(
    request: TravelRequest,
    *,
    today: date | None = None,
) -> list[FlightDateOption]:
    """Build at most three explicit date pairs without claiming fare availability or price."""

    current_date = today or date.today()
    horizon = current_date + timedelta(days=MAX_FLIGHT_SEARCH_HORIZON_DAYS)
    if exact_trip_dates_are_valid(request, today=current_date):
        assert request.date_from is not None
        assert request.date_to is not None
        return [
            FlightDateOption(
                departure_date=request.date_from,
                return_date=request.date_to,
                duration_nights=(request.date_to - request.date_from).days,
                date_mode="exact",
            )
        ]

    durations = _duration_choices(request)
    if not durations:
        return []

    if request.date_from is not None:
        if not current_date <= request.date_from <= horizon:
            return []
        return [
            FlightDateOption(
                departure_date=request.date_from,
                return_date=request.date_from + timedelta(days=duration),
                duration_nights=duration,
                date_mode="derived",
            )
            for duration in durations
            if request.date_from + timedelta(days=duration) <= horizon
        ][:3]

    if request.month is None:
        return []
    earliest, month_end = _next_month_bounds(request.month, current_date)
    positions = _position_choices(len(durations))

    def options_for_bounds(month_start: date, end: date) -> list[FlightDateOption]:
        options = [
            _month_option(
                earliest=month_start,
                month_end=end,
                duration_nights=duration,
                position=positions[index],
            )
            for index, duration in enumerate(durations)
        ]
        return [
            option for option in options if option is not None and option.return_date <= horizon
        ][:3]

    options = options_for_bounds(earliest, month_end)
    if options or request.month != current_date.month:
        return options
    next_year = current_date.year + 1
    next_start = date(next_year, request.month, 1)
    next_end = date(
        next_year,
        request.month,
        calendar.monthrange(next_year, request.month)[1],
    )
    return options_for_bounds(next_start, next_end)
