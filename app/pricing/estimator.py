"""Small deterministic modelled estimator for the demo catalog.

It deliberately does not claim provider availability.  Live/cached providers can replace the
component inputs later without changing the card contract.
"""

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from math import ceil
from typing import Literal

from app.domain.models import DestinationCandidate, TravelRequest
from app.pricing.models import (
    CostComponentEstimate,
    CostSourceSummary,
    MoneyRange,
    PriceBreakdownRow,
    PriceCardView,
    TripCostEstimate,
)

PRICING_VERSION = "demo-modelled-v1"


def estimate_trip_cost(candidate: DestinationCandidate, request: TravelRequest) -> TripCostEstimate:
    """Create a whole-party estimate from explicit local demo baseline components."""

    adults = request.adults or 1
    children, infants = request.children or 0, request.infants or 0
    party_weight = adults + children * 0.6 + infants * 0.2
    rooms = max(1, ceil(adults / 2))
    nights_min, nights_max = _nights(request)
    date_mode = _date_mode(request)
    observed_at = candidate.retrieved_at or datetime.now(UTC)
    source = CostSourceSummary(
        provider="local-demo-fixture",
        source_kind="modelled",
        observed_at=observed_at,
        url=candidate.sources[0].url if candidate.sources else None,
        confidence=0.4,
    )
    components = [
        _component(
            "flight",
            candidate.estimated_flight_cost_rub_min,
            candidate.estimated_flight_cost_rub_max,
            party_weight,
            source,
            "round trip для всей группы",
        ),
        _component(
            "stay",
            candidate.estimated_hotel_cost_rub_min,
            candidate.estimated_hotel_cost_rub_max,
            rooms,
            source,
            f"стандартное жильё, {rooms} номер(а)",
        ),
        _component(
            "daily",
            candidate.estimated_other_cost_rub,
            candidate.estimated_other_cost_rub,
            party_weight,
            source,
            "питание, городской транспорт и базовые активности",
        ),
        _component("required", 0, 0, 1, source, "нет отдельного подтверждённого сбора"),
    ]
    core_floor = sum(component.amount.low for component in components)
    core_expected = sum(component.amount.expected for component in components)
    core_safe = sum(component.amount.high for component in components)
    contingency = max(3_000, round(0.05 * components[2].amount.expected))
    components.extend(
        [
            _component(
                "recommended", 0, 0, 1, source, "страховка и необязательные рекомендации не оценены"
            ),
            CostComponentEstimate(
                component="contingency",
                amount=MoneyRange(low=0, expected=0, high=contingency),
                included_items=["небольшой запас на неопределённость"],
                sources=[source],
                confidence=0.4,
            ),
        ]
    )
    floor, expected, safe = core_floor, core_expected, core_safe + contingency
    budget = request.budget_total_rub
    fit = _budget_fit(floor, expected, safe, budget)
    request_hash = _hash(
        candidate.destination_id, request.model_dump(mode="json", exclude={"raw_query"})
    )
    scenario = _scenario_summary(adults, children, infants, nights_min, nights_max, date_mode)
    assumptions = [
        "Оценка построена по локальному modelled baseline, а не по текущему поиску поставщика.",
        "Цена рассчитана для всей указанной группы.",
    ]
    if date_mode != "exact":
        assumptions.append("Без точных дат сезонность и цены могут заметно отличаться.")
    if request.baggage_required:
        assumptions.append("Доплата за багаж не подтверждена отдельным источником.")
    return TripCostEstimate(
        pricing_snapshot_id=_hash(PRICING_VERSION, request_hash),
        pricing_version=PRICING_VERSION,
        request_hash=request_hash,
        scenario_summary=scenario,
        party_size=adults + children + infants,
        nights_min=nights_min,
        nights_max=nights_max,
        date_mode=date_mode,
        floor_total_rub=floor,
        expected_total_rub=expected,
        safe_total_rub=safe,
        budget_fit=fit,
        budget_gap_expected_rub=expected - budget if budget else None,
        budget_gap_safe_rub=safe - budget if budget else None,
        components=components,
        included_items=[
            "round trip",
            "вся группа",
            "стандартное жильё",
            "питание и городской транспорт",
            "небольшой запас",
        ],
        excluded_items=[
            "шопинг",
            "алкоголь",
            "дорогие экскурсии",
            "аренда автомобиля",
            "premium-активности",
        ],
        assumptions=assumptions,
        warnings=["Это модельный ориентир: цену и наличие нужно проверить у внешнего сервиса."],
        confidence=0.4,
        confidence_label="low",
        calculated_at=observed_at,
    )


def price_card_view(estimate: TripCostEstimate) -> PriceCardView:
    labels = {
        "confidently_within": "Вписывается с запасом",
        "likely_within": "Вписывается, но запас небольшой",
        "possible_with_savings": "Только при экономии",
        "over_budget": "Выше бюджета",
        "unknown": "Недостаточно данных о бюджете",
    }
    names = {
        "flight": "Перелёт",
        "stay": "Жильё",
        "daily": "На месте",
        "required": "Обязательные сборы",
        "contingency": "Запас",
    }
    rows = [
        PriceBreakdownRow(
            label=names[component.component],
            value=_range_label(component.amount.low, component.amount.high),
        )
        for component in estimate.components
        if component.component in names and component.amount.high
    ]
    return PriceCardView(
        headline=f"≈ {_rub(estimate.expected_total_rub)}–{_rub(estimate.safe_total_rub)}",
        subtitle=estimate.scenario_summary,
        floor_label=f"от {_rub(estimate.floor_total_rub)} при экономии",
        budget_status_label=labels[estimate.budget_fit],
        freshness_label="Модельный baseline из локального каталога",
        confidence_label="низкая уверенность",
        breakdown_rows=rows,
        included_items=estimate.included_items,
        excluded_items=estimate.excluded_items,
        warnings=estimate.warnings,
    )


def _component(
    component: Literal["flight", "stay", "daily", "required", "recommended", "contingency"],
    low: int | None,
    high: int | None,
    multiplier: float,
    source: CostSourceSummary,
    included: str,
) -> CostComponentEstimate:
    low, high = (
        round((low or 0) * multiplier),
        round((high if high is not None else low or 0) * multiplier),
    )
    expected = round(low + (high - low) * 0.5)
    return CostComponentEstimate(
        component=component,
        amount=MoneyRange(low=low, expected=expected, high=high),
        included_items=[included],
        sources=[source],
        confidence=0.4,
    )


def _nights(request: TravelRequest) -> tuple[int, int]:
    if request.date_from and request.date_to:
        nights = max(1, (request.date_to - request.date_from).days)
        return nights, nights
    return (
        request.duration_nights_min or 7,
        request.duration_nights_max or request.duration_nights_min or 7,
    )


def _date_mode(request: TravelRequest) -> Literal["exact", "flex_window", "month", "unknown"]:
    if request.date_from and request.date_to:
        return "exact"
    if request.departure_window_from:
        return "flex_window"
    if request.month:
        return "month"
    return "unknown"


def _budget_fit(
    floor: int, expected: int, safe: int, budget: int | None
) -> Literal[
    "confidently_within", "likely_within", "possible_with_savings", "over_budget", "unknown"
]:
    if budget is None:
        return "unknown"
    if safe <= budget:
        return "confidently_within"
    if expected <= budget:
        return "likely_within"
    if floor <= budget:
        return "possible_with_savings"
    return "over_budget"


def _scenario_summary(
    adults: int,
    children: int,
    infants: int,
    nights_min: int,
    nights_max: int,
    date_mode: Literal["exact", "flex_window", "month", "unknown"],
) -> str:
    people = (
        f"{adults} взросл."
        + (f", {children} ребёнка" if children else "")
        + (f", {infants} младенца" if infants else "")
    )
    nights = (
        f"{nights_min} ночей" if nights_min == nights_max else f"{nights_min}–{nights_max} ночей"
    )
    timing = {
        "exact": "точные даты",
        "flex_window": "гибкие даты",
        "month": "выбранный месяц",
        "unknown": "без точных дат",
    }[date_mode]
    return f"на {people} · {nights} · {timing}"


def _hash(*values: object) -> str:
    return sha256(repr(values).encode()).hexdigest()[:24]


def _rub(value: int) -> str:
    return f"{value:,} ₽".replace(",", " ")


def _range_label(low: int, high: int) -> str:
    return _rub(high) if low == high else f"{_rub(low)}–{_rub(high)}"
