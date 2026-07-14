"""Deterministic Aviasales handoff using origin and destination only."""

from __future__ import annotations

from urllib.parse import urlencode

from app.domain.models import ExternalTravelLink, ScoredDestination, TravelRequest

AVIASALES_BASE_URL = "https://www.aviasales.ru/"
AVIASALES_ROUTES_URL = "https://www.aviasales.ru/routes"

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
    """Build a route page and leave dates and passengers to the provider UI."""

    origin = _origin_iata(request.origin_city)
    if origin is None or not destination_iata:
        return _with_marker(AVIASALES_BASE_URL, marker)
    destination = destination_iata.upper()
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
            title="Выбрать даты",
            provider="aviasales",
            category="flight",
            url=url,
        )
        enriched_candidate = candidate.model_copy(
            update={"external_links": [flight_link, *other_links]}
        )
        enriched.append(recommendation.model_copy(update={"candidate": enriched_candidate}))
    return enriched
