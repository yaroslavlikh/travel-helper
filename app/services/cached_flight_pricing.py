"""Bridge cached Aviasales signals into cards without manufacturing a trip total."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime

from app.domain.models import DestinationCandidate, TravelRequest
from app.pricing.errors import CachedFlightProviderError
from app.pricing.models import FlightPriceSignal, PricingRequest, ScenarioBatch
from app.pricing.ports.flights import CachedFlightDiscovery
from app.pricing.scenario_generation import generate_date_scenarios
from app.services.aviasales import origin_iata

LOGGER = logging.getLogger(__name__)
DISCOVERY_SCENARIO_LIMIT = 5


async def discover_cached_flights(
    *,
    request: TravelRequest,
    candidates: list[DestinationCandidate],
    provider: CachedFlightDiscovery,
    now: datetime | None = None,
) -> dict[str, tuple[FlightPriceSignal, ...]]:
    """Return cached flight evidence per destination, with no invented fallback price."""

    observed_at = now or datetime.now(UTC)
    results: dict[str, tuple[FlightPriceSignal, ...]] = {}
    for candidate in candidates:
        pricing_request = pricing_request_for_candidate(request, candidate)
        if pricing_request is None:
            continue
        try:
            signals = await provider.search(
                pricing_request, _discovery_scenarios(pricing_request), now=observed_at
            )
        except CachedFlightProviderError as error:
            LOGGER.warning(
                "Cached flight discovery unavailable",
                extra={
                    "destination_id": candidate.destination_id,
                    "error_type": type(error).__name__,
                },
            )
            continue
        if signals:
            results[candidate.destination_id] = signals
    return results


def pricing_request_for_candidate(
    request: TravelRequest, candidate: DestinationCandidate
) -> PricingRequest | None:
    """Map only sufficient round-trip conditions into the deterministic pricing boundary."""

    origin = origin_iata(request.origin_city)
    destination = candidate.nearest_airport
    if origin is None or destination is None or request.flight_one_way:
        return None
    assert request.origin_city is not None
    origin_city_id = request.origin_city.casefold()
    adults = request.adults or 1
    children = request.children or 0
    if request.date_from is not None and request.date_to is not None:
        nights = (request.date_to - request.date_from).days
        if nights < 1:
            return None
        return PricingRequest(
            request_id=f"cached-{candidate.destination_id}",
            origin_city_id=origin_city_id,
            origin_iata=(origin,),
            destination_id=candidate.destination_id,
            destination_iata=(destination,),
            date_mode="exact",
            outbound_date=request.date_from,
            return_date=request.date_to,
            nights_min=nights,
            nights_max=nights,
            adults=adults,
            children_ages=tuple(8 for _ in range(children)),
            infants=request.infants or 0,
            rooms=1,
            max_flight_minutes=(
                round(request.max_flight_duration_hours * 60)
                if request.max_flight_duration_hours is not None
                else None
            ),
        )
    nights_min = request.duration_nights_min or 7
    nights_max = request.duration_nights_max or nights_min
    common = dict(
        request_id=f"cached-{candidate.destination_id}",
        origin_city_id=origin_city_id,
        origin_iata=(origin,),
        destination_id=candidate.destination_id,
        destination_iata=(destination,),
        nights_min=nights_min,
        nights_max=nights_max,
        adults=adults,
        children_ages=tuple(8 for _ in range(children)),
        infants=request.infants or 0,
        rooms=1,
        max_flight_minutes=(
            round(request.max_flight_duration_hours * 60)
            if request.max_flight_duration_hours is not None
            else None
        ),
    )
    if request.departure_window_from is not None and request.departure_window_to is not None:
        return PricingRequest.model_validate(
            {
                **common,
                "date_mode": "window",
                "departure_from": request.departure_window_from,
                "departure_to": request.departure_window_to,
            }
        )
    if request.month is None:
        return None
    today = date.today()
    year = today.year + int(request.month < today.month)
    return PricingRequest.model_validate(
        {**common, "date_mode": "month", "month": f"{year}-{request.month:02}"}
    )


def _discovery_scenarios(request: PricingRequest) -> ScenarioBatch:
    batch = generate_date_scenarios(request)
    if len(batch.scenarios) <= DISCOVERY_SCENARIO_LIMIT:
        return batch
    indexes = {
        round(index * (len(batch.scenarios) - 1) / (DISCOVERY_SCENARIO_LIMIT - 1))
        for index in range(DISCOVERY_SCENARIO_LIMIT)
    }
    return ScenarioBatch(
        generated_count=batch.generated_count,
        scenarios=tuple(batch.scenarios[index] for index in sorted(indexes)),
        sampling_applied=True,
    )


def preferred_cached_signal(signals: tuple[FlightPriceSignal, ...]) -> FlightPriceSignal | None:
    """Pick one reproducible display signal without treating it as an offer."""

    return min(
        signals,
        key=lambda signal: (
            signal.amount_rub,
            signal.age_hours if signal.age_hours is not None else 10_000,
            signal.outbound_date,
            signal.return_date,
            signal.signal_id,
        ),
        default=None,
    )


def apply_cached_flight_logistics(
    candidates: list[DestinationCandidate],
    signals_by_destination: dict[str, tuple[FlightPriceSignal, ...]],
) -> list[DestinationCandidate]:
    """Use observed duration/transfers in logistics scoring, never the cached amount as total."""

    enriched: list[DestinationCandidate] = []
    for candidate in candidates:
        signal = preferred_cached_signal(signals_by_destination.get(candidate.destination_id, ()))
        if signal is None:
            enriched.append(candidate)
            continue
        enriched.append(
            candidate.model_copy(
                update={
                    "flight_duration_hours": (
                        round(signal.duration_minutes / 60, 1)
                        if signal.duration_minutes is not None
                        else candidate.flight_duration_hours
                    ),
                    "transfers_count": (
                        signal.stops if signal.stops is not None else candidate.transfers_count
                    ),
                }
            )
        )
    return enriched
