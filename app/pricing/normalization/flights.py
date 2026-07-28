"""Provider-neutral live flight filters and deterministic price aggregation."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.pricing.config import (
    FLIGHT_AGGREGATION_CONFIG,
    FlightAggregationConfig,
)
from app.pricing.models import (
    CostComponent,
    DateScenario,
    FlightOffer,
    MoneyRange,
    PricingRequest,
)


def aggregate_flight_offers(
    *,
    request: PricingRequest,
    scenario: DateScenario,
    offers: tuple[FlightOffer, ...],
    now: datetime,
    config: FlightAggregationConfig = FLIGHT_AGGREGATION_CONFIG,
) -> CostComponent:
    """Return a full-party flight component or explicit missing evidence."""

    if now.tzinfo is None:
        raise ValueError("flight aggregation clock must be timezone-aware")
    valid = [
        offer
        for offer in offers
        if _passes_hard_checks(offer, request=request, scenario=scenario, now=now)
    ]
    unique: dict[str, FlightOffer] = {}
    for offer in sorted(valid, key=lambda item: (_total(item, request), item.offer_id)):
        unique.setdefault(offer.itinerary_key, offer)
    deduplicated = list(unique.values())
    floor_candidates = _remove_unverified_bait_prices(deduplicated, request, config)
    expected_candidates = [
        offer for offer in floor_candidates if _has_acceptable_baggage(offer, request)
    ]
    if not expected_candidates:
        return CostComponent(
            scenario_id=scenario.scenario_id,
            name="flight",
            amount=None,
            status="missing",
            included=(),
            excluded=("неподтверждённая стоимость требуемого багажа",),
            warnings=("Есть только неполные flight offers; expected/safe не рассчитаны.",),
            sources=tuple(dict.fromkeys(offer.source for offer in floor_candidates)),
        )

    expected_values = sorted(_total(offer, request) for offer in expected_candidates)
    floor_values = sorted(_total(offer, request) for offer in floor_candidates)
    floor = floor_values[0] if floor_values else expected_values[0]
    expected, safe = _expected_and_safe(expected_values, config)
    amount = MoneyRange(
        floor=_rubles(floor),
        expected=_rubles(expected),
        safe=_rubles(safe),
    )
    used_sources = tuple(
        dict.fromkeys(offer.source for offer in [*floor_candidates, *expected_candidates])
    )
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="flight",
        amount=amount,
        status="available",
        included=(
            "перелёт туда-обратно",
            "вся указанная группа",
            "налоги и обязательные сборы",
            *(("подтверждённый требуемый багаж",) if request.baggage != "not_required" else ()),
        ),
        excluded=(
            ()
            if request.baggage == "not_required"
            else ("дополнительный багаж сверх подтверждённого",)
        ),
        assumptions=(
            "Flight expected — медиана дешёвых приемлемых live offers; safe — верхний квартиль.",
        ),
        warnings=(
            ("Часть подозрительно дешёвых offers исключена из floor.",)
            if len(floor_candidates) < len(deduplicated)
            else ()
        ),
        sources=used_sources,
    )


def _passes_hard_checks(
    offer: FlightOffer,
    *,
    request: PricingRequest,
    scenario: DateScenario,
    now: datetime,
) -> bool:
    return (
        offer.scenario_id == scenario.scenario_id
        and offer.origin_iata in request.origin_iata
        and offer.destination_iata in request.destination_iata
        and offer.outbound_departure.date() == scenario.outbound_date
        and offer.return_departure.date() == scenario.return_date
        and offer.adults == request.adults
        and offer.children == len(request.children_ages)
        and offer.infants == request.infants
        and offer.taxes_included
        and offer.mandatory_fees_included
        and (offer.expires_at is None or offer.expires_at > now)
        and (
            request.max_stops is None
            or max(offer.stops_outbound, offer.stops_return) <= request.max_stops
        )
        and (
            request.max_flight_minutes is None
            or offer.duration_minutes_total <= request.max_flight_minutes
        )
        and (request.allow_self_transfer or not offer.self_transfer)
    )


def _has_acceptable_baggage(offer: FlightOffer, request: PricingRequest) -> bool:
    if not offer.revalidated:
        return False
    if request.baggage == "not_required":
        return True
    return offer.baggage_status in {"included", "known_extra_price"}


def _remove_unverified_bait_prices(
    offers: list[FlightOffer],
    request: PricingRequest,
    config: FlightAggregationConfig,
) -> list[FlightOffer]:
    ordered = sorted(offers, key=lambda offer: _total(offer, request))
    if len(ordered) < 2:
        return ordered
    benchmark = Decimal(
        str(median(_total(offer, request) for offer in ordered[: config.bait_median_count]))
    )
    threshold = benchmark * config.bait_price_ratio
    return [
        offer
        for offer in ordered
        if _total(offer, request) >= threshold
        or (offer.revalidated and offer.baggage_status in {"included", "known_extra_price"})
    ]


def _expected_and_safe(
    values: list[Decimal],
    config: FlightAggregationConfig,
) -> tuple[Decimal, Decimal]:
    if len(values) == 1:
        return values[0], values[0]
    if len(values) == 2:
        return values[1], values[1]
    expected = Decimal(str(median(values[: config.expected_offer_count])))
    if len(values) < config.safe_offer_count:
        return expected, values[-1]
    return expected, _percentile(values[: config.safe_offer_count], config.safe_percentile)


def _percentile(values: list[Decimal], percentile: int) -> Decimal:
    position = Decimal(percentile) / Decimal(100) * Decimal(len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + fraction * (values[upper] - values[lower])


def _total(offer: FlightOffer, request: PricingRequest) -> Decimal:
    if request.baggage != "not_required" and offer.baggage_extra_rub is not None:
        return offer.total_rub + offer.baggage_extra_rub
    return offer.total_rub


def _rubles(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
