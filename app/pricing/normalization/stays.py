"""Provider-neutral stay filtering and cheapest-acceptable-basket aggregation."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from statistics import median

from app.pricing.config import STAY_AGGREGATION_CONFIG, StayAggregationConfig
from app.pricing.models import (
    CostComponent,
    DateScenario,
    MoneyRange,
    PricingRequest,
    StayOffer,
    StayProfileRules,
)


def aggregate_stay_offers(
    *,
    request: PricingRequest,
    scenario: DateScenario,
    offers: tuple[StayOffer, ...],
    rules: StayProfileRules,
    config: StayAggregationConfig = STAY_AGGREGATION_CONFIG,
) -> CostComponent:
    """Aggregate exact whole-party stay totals without nightly/room multiplication."""

    if rules.profile != request.accommodation_profile:
        raise ValueError("stay profile rules do not match request")
    valid = [
        offer for offer in offers if _passes(offer, request=request, scenario=scenario, rules=rules)
    ]
    unique: dict[tuple[str, str, str], StayOffer] = {}
    for offer in sorted(valid, key=lambda item: (_total(item), item.offer_id)):
        key = (offer.property_id, offer.product_id, offer.cancellation)
        unique.setdefault(key, offer)
    basket = sorted(unique.values(), key=_total)[: config.safe_offer_count]
    basket = _remove_low_outlier(basket, config)
    if not basket:
        return CostComponent(
            scenario_id=scenario.scenario_id,
            name="stay",
            amount=None,
            status="missing",
            included=(),
            excluded=("неподходящие или неполные варианты проживания",),
            warnings=("Нет live stay offers, проходящих профиль и occupancy.",),
            sources=(),
        )
    values = [_total(offer) for offer in basket]
    floor = values[0]
    if len(values) == 1:
        expected = safe = values[0]
    elif len(values) <= 4:
        expected = Decimal(str(median(values)))
        safe = values[-1]
    else:
        expected = Decimal(str(median(values[: config.expected_offer_count])))
        safe = _percentile(values, config.safe_percentile)
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="stay",
        amount=MoneyRange(
            floor=_rubles(floor),
            expected=_rubles(expected),
            safe=_rubles(safe),
        ),
        status="available",
        included=(
            f"{request.rooms} номер(а)",
            f"{scenario.nights} ночей",
            "вся указанная группа",
            "обязательные исключённые сборы",
        ),
        excluded=("условные и необязательные услуги объекта",),
        assumptions=(
            f"Профиль жилья: {rules.profile}; правила {rules.rules_version}.",
            "Provider total уже относится ко всем комнатам и ночам и не умножается повторно.",
        ),
        warnings=(
            ("Нижний ценовой outlier исключён из корзины.",)
            if len(basket) < min(len(unique), config.safe_offer_count)
            else ()
        ),
        sources=tuple(dict.fromkeys(offer.source for offer in basket)),
    )


def _passes(
    offer: StayOffer,
    *,
    request: PricingRequest,
    scenario: DateScenario,
    rules: StayProfileRules,
) -> bool:
    return (
        offer.scenario_id == scenario.scenario_id
        and offer.checkin == scenario.outbound_date
        and offer.checkout == scenario.return_date
        and offer.adults == request.adults
        and offer.children == len(request.children_ages)
        and offer.rooms == request.rooms
        and offer.covers_full_stay
        and offer.covers_full_party
        and offer.mandatory_charges_complete
        and (not offer.dorm or request.allow_dorm)
        and (not rules.require_private_room or offer.private_room)
        and (rules.allow_shared_bathroom or not offer.shared_bathroom)
        and (not rules.require_preferred_area or offer.in_preferred_area is True)
        and offer.rating is not None
        and offer.rating >= rules.minimum_rating
        and (offer.review_count is None or offer.review_count >= rules.minimum_review_count)
        and offer.distance_center_km <= rules.maximum_distance_km
        and (not rules.require_flexible_cancellation or offer.cancellation == "flexible")
    )


def _remove_low_outlier(offers: list[StayOffer], config: StayAggregationConfig) -> list[StayOffer]:
    if len(offers) < 2:
        return offers
    benchmark = Decimal(
        str(median(_total(offer) for offer in offers[: config.outlier_median_count]))
    )
    threshold = benchmark * config.outlier_ratio
    return [offer for offer in offers if _total(offer) >= threshold]


def _total(offer: StayOffer) -> Decimal:
    return offer.total_rub + offer.mandatory_excluded_rub + offer.extra_local_transport_rub


def _percentile(values: list[Decimal], percentile: int) -> Decimal:
    position = Decimal(percentile) / Decimal(100) * Decimal(len(values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + fraction * (values[upper] - values[lower])


def _rubles(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
