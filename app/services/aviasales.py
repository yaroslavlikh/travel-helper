"""Deterministic Aviasales handoff that uses dates only when they are exact."""

from __future__ import annotations

from urllib.parse import urlencode

from app.domain.models import ExternalTravelLink, ScoredDestination, TravelRequest

AVIASALES_BASE_URL = "https://www.aviasales.ru/"
AVIASALES_ROUTES_URL = "https://www.aviasales.ru/routes"
AVIASALES_SEARCH_URL = "https://www.aviasales.ru/search/"

CITY_IATA = {
    "москва": "MOW",
    "мск": "MOW",
    "moscow": "MOW",
    "mow": "MOW",
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


def _with_marker(url: str, marker: str | None) -> str:
    if not marker:
        return url
    return f"{url}?{urlencode({'marker': marker})}"


def build_aviasales_url(
    request: TravelRequest,
    *,
    destination_iata: str | None,
    marker: str | None = None,
) -> str:
    """Build an exact search only for an explicit round trip or one-way date."""

    origin = _origin_iata(request.origin_city)
    if origin is None or not destination_iata:
        return _with_marker(AVIASALES_BASE_URL, marker)
    destination = destination_iata.upper()
    if request.date_from and (request.date_to or request.flight_one_way):
        params: dict[str, str | int] = {
            "origin_iata": origin,
            "destination_iata": destination,
            "depart_date": request.date_from.isoformat(),
            "oneway": int(bool(request.flight_one_way)),
            "adults": request.adults or 1,
            "children": request.children or 0,
            "infants": request.infants or 0,
            "trip_class": 0,
        }
        if request.date_to and not request.flight_one_way:
            params["return_date"] = request.date_to.isoformat()
        if marker:
            params["marker"] = marker
        return f"{AVIASALES_SEARCH_URL}?{urlencode(params)}"
    return _with_marker(
        f"{AVIASALES_ROUTES_URL}/{origin.casefold()}/{destination.casefold()}",
        marker,
    )


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
        url = build_aviasales_url(
            request,
            destination_iata=candidate.nearest_airport,
            marker=marker,
        )
        flight_link = ExternalTravelLink(
            title="Найти билеты"
            if request.date_from and (request.date_to or request.flight_one_way)
            else "Выбрать даты",
            provider="aviasales",
            category="flight",
            url=url,
        )
        enriched_candidate = candidate.model_copy(
            update={"external_links": [flight_link, *other_links]}
        )
        enriched.append(recommendation.model_copy(update={"candidate": enriched_candidate}))
    return enriched
