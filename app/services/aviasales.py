"""Deterministic Aviasales handoff using the canonical compact web routes."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlencode

from app.domain.models import ExternalTravelLink, ScoredDestination, TravelRequest

AVIASALES_BASE_URL = "https://www.aviasales.ru/"
AVIASALES_SEARCH_URL = "https://www.aviasales.ru/search"
AVIASALES_ROUTES_URL = "https://www.aviasales.ru/routes"
MAX_SEARCH_HORIZON_DAYS = 365
MONTHS_SHORT_RU = (
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
)

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
    departure = request.flight_departure_date or request.date_from
    returning = request.flight_return_date or request.date_to
    horizon = today + timedelta(days=MAX_SEARCH_HORIZON_DAYS)
    if departure is None or not today <= departure <= horizon:
        return None
    if request.flight_one_way is True:
        return departure, None
    if returning is None or not departure < returning <= horizon:
        return None
    return departure, returning


def _with_marker(url: str, marker: str | None) -> str:
    if not marker:
        return url
    return f"{url}?{urlencode({'marker': marker})}"


def _compact_search_url(
    *,
    origin: str,
    destination: str,
    departure: date,
    returning: date | None,
    adults: int,
) -> str:
    route = f"{origin}{departure:%d%m}{destination}"
    if returning is not None:
        route += f"{returning:%d%m}"
    return f"{AVIASALES_SEARCH_URL}/{route}{adults}"


def build_aviasales_url(
    request: TravelRequest,
    *,
    destination_iata: str | None,
    marker: str | None = None,
    today: date | None = None,
) -> str:
    """Build a compact exact search or a route page for provider-side date selection."""

    current_date = today or date.today()
    origin = _origin_iata(request.origin_city)
    if origin is None or not destination_iata:
        return _with_marker(AVIASALES_BASE_URL, marker)
    destination = destination_iata.upper()

    confirmed_dates = _confirmed_flight_dates(request, today=current_date)
    adults = request.adults or 1
    family_details_are_safe = not request.children and not request.infants
    if confirmed_dates is not None and family_details_are_safe and 1 <= adults <= 9:
        departure, returning = confirmed_dates
        return _with_marker(
            _compact_search_url(
                origin=origin,
                destination=destination,
                departure=departure,
                returning=returning,
                adults=adults,
            ),
            marker,
        )
    return _with_marker(
        f"{AVIASALES_ROUTES_URL}/{origin.casefold()}/{destination.casefold()}",
        marker,
    )


def _flight_link_title(request: TravelRequest, url: str) -> str:
    dates = _confirmed_flight_dates(request, today=date.today())
    if dates is None or "/search/" not in url:
        return "Выбрать даты"
    departure, returning = dates
    if returning is None:
        return f"Билеты {departure.day} {MONTHS_SHORT_RU[departure.month - 1]}"
    return f"Билеты {departure.day}–{returning.day} {MONTHS_SHORT_RU[returning.month - 1]}"


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
            title=_flight_link_title(request, url),
            provider="aviasales",
            category="flight",
            url=url,
        )
        enriched_candidate = candidate.model_copy(
            update={"external_links": [flight_link, *other_links]}
        )
        enriched.append(recommendation.model_copy(update={"candidate": enriched_candidate}))
    return enriched
