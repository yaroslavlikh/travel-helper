"""Deterministic Aviasales handoff without invented dates or provider defaults."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from app.domain.models import ExternalTravelLink, ScoredDestination, TravelRequest

AVIASALES_SEARCH_URL = "https://www.aviasales.ru/search"
MAX_SEARCH_HORIZON_DAYS = 365

CITY_IATA = {
    "москва": "MOW",
    "санкт-петербург": "LED",
    "петербург": "LED",
    "спб": "LED",
    "екатеринбург": "SVX",
    "казань": "KZN",
    "новосибирск": "OVB",
    "сочи": "AER",
}


def _origin_iata(origin_city: str | None) -> str | None:
    if origin_city is None:
        return None
    return CITY_IATA.get(origin_city.strip().casefold())


def _confirmed_flight_dates(
    request: TravelRequest,
    *,
    today: date,
) -> tuple[date, date | None] | None:
    departure = request.flight_departure_date
    returning = request.flight_return_date
    horizon = today + timedelta(days=MAX_SEARCH_HORIZON_DAYS)
    if departure is None or not today <= departure <= horizon:
        return None
    if request.flight_one_way is True:
        return departure, None
    if returning is None or not departure < returning <= horizon:
        return None
    return departure, returning


def build_aviasales_url(
    request: TravelRequest,
    *,
    destination_iata: str | None,
    marker: str | None = None,
    today: date | None = None,
) -> str:
    """Build the documented search URL; omit any value that is not provider-safe."""

    current_date = today or date.today()
    params: list[tuple[str, str]] = []
    origin = _origin_iata(request.origin_city)
    if origin is not None and destination_iata:
        params.append(("origin_iata", origin))
        params.append(("destination_iata", destination_iata.upper()))

    confirmed_dates = _confirmed_flight_dates(request, today=current_date)
    if origin is not None and destination_iata and confirmed_dates is not None:
        departure, returning = confirmed_dates
        params.append(("depart_date", departure.isoformat()))
        if returning is None:
            params.append(("oneway", "1"))
        else:
            params.extend((("return_date", returning.isoformat()), ("oneway", "0")))

    params.extend(
        (
            ("adults", str(request.adults or 1)),
            ("children", str(request.children or 0)),
            ("infants", str(request.infants or 0)),
            ("trip_class", "0"),
            ("currency", "RUB"),
        )
    )
    if marker:
        params.append(("marker", marker))
    return f"{AVIASALES_SEARCH_URL}?{urlencode(params)}"


def add_aviasales_links(
    recommendations: list[ScoredDestination],
    request: TravelRequest,
    *,
    marker: str | None = None,
) -> list[ScoredDestination]:
    """Return request-scoped copies with one replaceable flight routing link per card."""

    enriched: list[ScoredDestination] = []
    for recommendation in recommendations:
        candidate = recommendation.candidate
        other_links = [link for link in candidate.external_links if link.category != "flight"]
        flight_link = ExternalTravelLink(
            title="Найти билеты",
            provider="aviasales",
            category="flight",
            url=build_aviasales_url(
                request,
                destination_iata=candidate.nearest_airport,
                marker=marker,
            ),
        )
        enriched_candidate = candidate.model_copy(
            update={"external_links": [flight_link, *other_links]}
        )
        enriched.append(recommendation.model_copy(update={"candidate": enriched_candidate}))
    return enriched
