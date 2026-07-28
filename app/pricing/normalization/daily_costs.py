"""Deterministic food and public-transit component calculations."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from app.pricing.config import DAILY_COST_CONFIG, DailyCostConfig
from app.pricing.models import (
    ChildTransitFare,
    ComponentName,
    CostComponent,
    DateScenario,
    FoodPriceSet,
    MoneyRange,
    PriceTriple,
    PricingRequest,
    TransitFareSet,
)


def calculate_food_component(
    *,
    request: PricingRequest,
    scenario: DateScenario,
    prices: FoodPriceSet,
    config: DailyCostConfig = DAILY_COST_CONFIG,
) -> CostComponent:
    """Price a fixed alcohol-free food basket for the full party."""

    if request.spending_profile == "comfort":
        return _missing(
            scenario=scenario,
            name="food",
            warning="Comfort food profile не откалиброван.",
        )
    if request.spending_profile == "standard" and prices.cappuccino is None:
        return _missing(
            scenario=scenario,
            name="food",
            warning="Для standard food profile отсутствует цена cappuccino.",
        )

    adult_daily = _adult_food_daily(prices, request.spending_profile)
    party_factor = Decimal(request.adults)
    party_factor += Decimal(request.infants) * config.infant_food_factor
    party_factor += sum(
        (_child_food_factor(age, config) for age in request.children_ages),
        start=Decimal(0),
    )
    days = Decimal(scenario.nights)
    amount = MoneyRange(
        floor=_rubles(adult_daily.low * party_factor * days),
        expected=_rubles(adult_daily.average * party_factor * days),
        safe=_rubles(adult_daily.high * party_factor * days),
    )
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="food",
        amount=amount,
        status="available",
        included=("фиксированная корзина без алкоголя", "первый и последний день по 0.5"),
        excluded=("алкоголь", "индивидуальные диеты и ресторанные add-ons"),
        assumptions=(
            f"Food profile: {request.spending_profile}; config {config.version}.",
            f"Effective spend days: {scenario.nights}.",
        ),
        sources=prices.sources,
    )


def calculate_local_transport_component(
    *,
    request: PricingRequest,
    scenario: DateScenario,
    fares: TransitFareSet,
    config: DailyCostConfig = DAILY_COST_CONFIG,
) -> CostComponent:
    """Price official public-transit fares; taxis are deliberately excluded."""

    rides = {
        "economy": config.economy_transit_rides_per_day,
        "standard": config.standard_transit_rides_per_day,
        "comfort": config.comfort_transit_rides_per_day,
    }[request.spending_profile]
    adult_total = _transit_person_total(
        days=scenario.nights,
        rides_per_day=rides,
        single=fares.adult_single_ride_rub,
        day_pass=fares.adult_day_pass_rub,
        weekly_pass=fares.adult_weekly_pass_rub,
    )
    total = adult_total * request.adults
    missing_child_ages: list[int] = []
    for age in (*((1,) * request.infants), *request.children_ages):
        child_fare = _child_transit_fare(age, fares.child_fares)
        if child_fare is None:
            missing_child_ages.append(age)
            continue
        total += _transit_person_total(
            days=scenario.nights,
            rides_per_day=rides,
            single=child_fare.single_ride_rub,
            day_pass=child_fare.day_pass_rub,
            weekly_pass=child_fare.weekly_pass_rub,
        )
    if missing_child_ages:
        ages = ", ".join(str(age) for age in sorted(set(missing_child_ages)))
        return _missing(
            scenario=scenario,
            name="local_transport",
            warning=f"Нет официального детского тарифа для возраста: {ages}.",
        )
    rounded = _rubles(total)
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name="local_transport",
        amount=MoneyRange(floor=rounded, expected=rounded, safe=rounded),
        status="available",
        included=("официальный городской общественный транспорт",),
        excluded=("такси", "airport transfer"),
        assumptions=(
            f"{rides} поездки в день; config {config.version}.",
            "Использован минимальный применимый тариф: разовые, day pass или weekly pass.",
        ),
        sources=fares.sources,
    )


def _adult_food_daily(
    prices: FoodPriceSet,
    profile: str,
) -> PriceTriple:
    grocery = prices.grocery_daily_basket
    meal = prices.inexpensive_meal
    combo = prices.fast_food_combo
    water = prices.water_small
    if profile == "economy":
        return PriceTriple(
            low=Decimal("0.70") * grocery.low + combo.low + water.low,
            average=Decimal("0.60") * grocery.average + meal.low + water.average,
            high=(
                Decimal("0.50") * grocery.high
                + meal.average
                + combo.average
                + Decimal(2) * water.high
            ),
        )
    cappuccino = prices.cappuccino
    if cappuccino is None:
        raise ValueError("standard food profile requires cappuccino prices")
    return PriceTriple(
        low=(Decimal("0.50") * grocery.low + meal.low + combo.low + water.low),
        average=(
            Decimal("0.40") * grocery.average
            + Decimal(2) * meal.average
            + Decimal(2) * water.average
        ),
        high=(
            Decimal("0.30") * grocery.high
            + Decimal(2) * meal.high
            + combo.average
            + Decimal(2) * water.high
            + cappuccino.average
        ),
    )


def _child_food_factor(age: int, config: DailyCostConfig) -> Decimal:
    if age <= 2:
        return config.infant_food_factor
    for age_min, age_max, factor in config.child_food_factors:
        if age_min <= age <= age_max:
            return factor
    raise ValueError(f"missing food factor for child age {age}")


def _transit_person_total(
    *,
    days: int,
    rides_per_day: int,
    single: Decimal,
    day_pass: Decimal | None,
    weekly_pass: Decimal | None,
) -> Decimal:
    ride_based = single * rides_per_day
    daily = min(ride_based, day_pass) if day_pass is not None else ride_based
    all_daily = daily * days
    if days < 7 or weekly_pass is None:
        return all_daily
    return min(all_daily, weekly_pass + daily * (days - 7))


def _child_transit_fare(
    age: int,
    fares: tuple[ChildTransitFare, ...],
) -> ChildTransitFare | None:
    return next(
        (fare for fare in fares if fare.age_min <= age <= fare.age_max),
        None,
    )


def _missing(
    *,
    scenario: DateScenario,
    name: ComponentName,
    warning: str,
) -> CostComponent:
    return CostComponent(
        scenario_id=scenario.scenario_id,
        name=name,
        amount=None,
        status="missing",
        warnings=(warning,),
    )


def _rubles(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
