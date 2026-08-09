"""Immutable public contracts for deterministic trip pricing."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

IATA_PATTERN = re.compile(r"^[A-Z]{3}$")
ISO_COUNTRY_PATTERN = re.compile(r"^[A-Z]{2}$")
MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")

DateMode = Literal["exact", "window", "month"]
ComponentName = Literal[
    "flight",
    "stay",
    "airport_transfer",
    "food",
    "local_transport",
    "activities",
    "mandatory_charges",
    "recommended",
]
ComponentStatus = Literal["available", "partial", "missing", "stale", "unsupported"]
SourceKind = Literal["live", "cached", "fixture", "manual", "derived"]
BaggageStatus = Literal[
    "included",
    "known_extra_price",
    "not_included_unknown_price",
    "unknown",
]


class PricingModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PricingRequest(PricingModel):
    request_id: str = Field(min_length=1, max_length=128)
    origin_city_id: str = Field(min_length=1, max_length=128)
    origin_iata: tuple[str, ...] = Field(min_length=1, max_length=8)
    destination_id: str = Field(min_length=1, max_length=128)
    destination_iata: tuple[str, ...] = Field(min_length=1, max_length=8)
    date_mode: DateMode
    outbound_date: date | None = None
    return_date: date | None = None
    departure_from: date | None = None
    departure_to: date | None = None
    month: str | None = None
    nights_min: int = Field(ge=1, le=30)
    nights_max: int = Field(ge=1, le=30)
    adults: int = Field(ge=1, le=9)
    children_ages: tuple[int, ...] = ()
    infants: int = Field(default=0, ge=0, le=6)
    rooms: int = Field(ge=1, le=5)
    cabin: Literal["economy"] = "economy"
    baggage: Literal["required", "not_required", "unknown"] = "unknown"
    accommodation_profile: Literal["economy", "standard", "comfort"] = "standard"
    spending_profile: Literal["economy", "standard", "comfort"] = "standard"
    citizenship_country: str | None = None
    booker_country: str = "RU"
    result_currency: Literal["RUB"] = "RUB"
    max_stops: int | None = Field(default=None, ge=0)
    max_flight_minutes: int | None = Field(default=None, gt=0)
    allow_self_transfer: bool = False
    allow_dorm: bool = False

    @field_validator("origin_iata", "destination_iata")
    @classmethod
    def validate_iata_codes(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(value.upper() for value in values)
        if len(set(normalized)) != len(normalized) or any(
            not IATA_PATTERN.fullmatch(value) for value in normalized
        ):
            raise ValueError("IATA codes must be unique three-letter codes")
        return normalized

    @field_validator("children_ages")
    @classmethod
    def validate_child_ages(cls, values: tuple[int, ...]) -> tuple[int, ...]:
        if any(age < 2 or age > 17 for age in values):
            raise ValueError(
                "children ages must be between 2 and 17; younger travellers are infants"
            )
        return values

    @field_validator("citizenship_country", "booker_country")
    @classmethod
    def validate_country_code(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.upper()
        if not ISO_COUNTRY_PATTERN.fullmatch(normalized):
            raise ValueError("country codes must use ISO alpha-2")
        return normalized

    @model_validator(mode="after")
    def validate_request_shape(self) -> PricingRequest:
        if self.nights_min > self.nights_max:
            raise ValueError("nights_min must not exceed nights_max")
        if self.infants > self.adults:
            raise ValueError("infants must not exceed adults")
        if self.adults + len(self.children_ages) + self.infants > 9:
            raise ValueError("total passenger count must not exceed 9")

        exact_fields = self.outbound_date is not None or self.return_date is not None
        window_fields = self.departure_from is not None or self.departure_to is not None
        month_field = self.month is not None
        if self.date_mode == "exact":
            if self.outbound_date is None or self.return_date is None:
                raise ValueError("exact mode requires outbound_date and return_date")
            if self.return_date <= self.outbound_date:
                raise ValueError("return_date must be after outbound_date")
            if window_fields or month_field:
                raise ValueError("exact mode cannot include window or month fields")
            nights = (self.return_date - self.outbound_date).days
            if not self.nights_min <= nights <= self.nights_max:
                raise ValueError("exact dates must fit the requested nights range")
        elif self.date_mode == "window":
            if self.departure_from is None or self.departure_to is None:
                raise ValueError("window mode requires departure_from and departure_to")
            if self.departure_to < self.departure_from:
                raise ValueError("departure_to must not precede departure_from")
            if exact_fields or month_field:
                raise ValueError("window mode cannot include exact or month fields")
        else:
            if self.month is None or not MONTH_PATTERN.fullmatch(self.month):
                raise ValueError("month mode requires YYYY-MM")
            if exact_fields or window_fields:
                raise ValueError("month mode cannot include exact or window fields")
        return self


class DateScenario(PricingModel):
    scenario_id: str = Field(min_length=8, max_length=64)
    outbound_date: date
    return_date: date
    nights: int = Field(ge=1, le=30)

    @model_validator(mode="after")
    def dates_match_nights(self) -> DateScenario:
        if (self.return_date - self.outbound_date).days != self.nights:
            raise ValueError("scenario dates must match nights")
        return self


class ScenarioBatch(PricingModel):
    generated_count: int = Field(ge=1)
    scenarios: tuple[DateScenario, ...] = Field(min_length=1)
    sampling_applied: bool = False

    @model_validator(mode="after")
    def counts_are_consistent(self) -> ScenarioBatch:
        if self.generated_count < len(self.scenarios):
            raise ValueError("generated_count cannot be smaller than selected scenarios")
        return self


class MoneyRange(PricingModel):
    currency: Literal["RUB"] = "RUB"
    floor: int = Field(ge=0)
    expected: int = Field(ge=0)
    safe: int = Field(ge=0)

    @model_validator(mode="after")
    def values_are_ordered(self) -> MoneyRange:
        if not self.floor <= self.expected <= self.safe:
            raise ValueError("money range must satisfy floor <= expected <= safe")
        return self


class SourceRef(PricingModel):
    source_id: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=128)
    source_kind: SourceKind
    observed_at: datetime
    valid_until: datetime | None = None
    source_url: str | None = None
    raw_reference_id: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validity_follows_observation(self) -> SourceRef:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if self.valid_until is not None and self.valid_until <= self.observed_at:
            raise ValueError("valid_until must be after observed_at")
        return self


class FxRate(PricingModel):
    char_code: str = Field(pattern=r"^[A-Z]{3}$")
    nominal: int = Field(ge=1)
    value_rub: Decimal = Field(gt=0)

    @property
    def rub_per_unit(self) -> Decimal:
        return self.value_rub / Decimal(self.nominal)


class FxRateTable(PricingModel):
    table_version: str
    effective_date: date
    fetched_at: datetime
    rates: tuple[FxRate, ...] = Field(min_length=1)
    source: SourceRef
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def rate_table_is_consistent(self) -> FxRateTable:
        if self.fetched_at.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        codes = [rate.char_code for rate in self.rates]
        if len(codes) != len(set(codes)):
            raise ValueError("FX table cannot contain duplicate currencies")
        return self

    def rate_for(self, char_code: str) -> FxRate:
        normalized = char_code.upper()
        try:
            return next(rate for rate in self.rates if rate.char_code == normalized)
        except StopIteration as error:
            raise KeyError(f"unsupported currency: {normalized}") from error


class FlightPriceSignal(PricingModel):
    """Cached route/date hint; never a full-party flight component."""

    signal_id: str = Field(min_length=8, max_length=128)
    scenario_id: str = Field(min_length=8, max_length=64)
    origin_iata: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata: str = Field(pattern=r"^[A-Z]{3}$")
    outbound_date: date
    return_date: date
    amount_rub: Decimal = Field(gt=0)
    currency: Literal["RUB"] = "RUB"
    airline: str | None = Field(default=None, min_length=2, max_length=8)
    stops: int | None = Field(default=None, ge=0)
    return_stops: int | None = Field(default=None, ge=0)
    duration_minutes: int | None = Field(default=None, gt=0)
    found_at: datetime | None = None
    expires_at: datetime | None = None
    fetched_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    age_hours: int | None = Field(default=None, ge=0)
    confidence: float = Field(default=0.5, ge=0, le=1)
    provider_url: str | None = Field(default=None, max_length=2_048)
    source: SourceRef
    price_basis: Literal["cached_unknown_party"] = "cached_unknown_party"
    usable_for_total: Literal[False] = False

    @model_validator(mode="after")
    def signal_is_consistent(self) -> FlightPriceSignal:
        if self.fetched_at.tzinfo is None or any(
            value is not None and value.tzinfo is None for value in (self.found_at, self.expires_at)
        ):
            raise ValueError("flight signal timestamps must be timezone-aware")
        if (
            self.found_at is not None
            and self.expires_at is not None
            and self.expires_at <= self.found_at
        ):
            raise ValueError("flight signal must expire after it was found")
        if self.found_at is not None and self.fetched_at < self.found_at:
            raise ValueError("flight signal cannot be fetched before it was found")
        if self.return_date <= self.outbound_date:
            raise ValueError("flight signal return date must follow outbound date")
        if self.source.source_kind != "cached":
            raise ValueError("flight price signal must be labelled cached")
        return self


class FlightOffer(PricingModel):
    provider: str = Field(min_length=1, max_length=128)
    offer_id: str = Field(min_length=1, max_length=256)
    scenario_id: str = Field(min_length=8, max_length=64)
    itinerary_key: str = Field(min_length=8, max_length=512)
    origin_iata: str = Field(pattern=r"^[A-Z]{3}$")
    destination_iata: str = Field(pattern=r"^[A-Z]{3}$")
    total_rub: Decimal = Field(gt=0)
    adults: int = Field(ge=1, le=9)
    children: int = Field(default=0, ge=0, le=8)
    infants: int = Field(default=0, ge=0, le=6)
    outbound_departure: datetime
    outbound_arrival: datetime
    return_departure: datetime
    return_arrival: datetime
    stops_outbound: int = Field(ge=0)
    stops_return: int = Field(ge=0)
    duration_minutes_total: int = Field(gt=0)
    baggage_status: BaggageStatus
    baggage_extra_rub: Decimal | None = Field(default=None, gt=0)
    taxes_included: bool
    mandatory_fees_included: bool
    self_transfer: bool
    revalidated: bool = False
    expires_at: datetime | None = None
    source: SourceRef

    @model_validator(mode="after")
    def offer_is_consistent(self) -> FlightOffer:
        timestamps = (
            self.outbound_departure,
            self.outbound_arrival,
            self.return_departure,
            self.return_arrival,
        )
        if any(value.tzinfo is None for value in timestamps):
            raise ValueError("flight timestamps must be timezone-aware")
        if not (
            self.outbound_departure < self.outbound_arrival
            and self.return_departure < self.return_arrival
            and self.outbound_arrival < self.return_departure
        ):
            raise ValueError("flight itinerary timestamps are inconsistent")
        if self.expires_at is not None and self.expires_at.tzinfo is None:
            raise ValueError("flight expiry must be timezone-aware")
        if self.baggage_status == "known_extra_price" and self.baggage_extra_rub is None:
            raise ValueError("known baggage extra requires its price")
        if self.baggage_status != "known_extra_price" and self.baggage_extra_rub is not None:
            raise ValueError("baggage extra is valid only for known_extra_price")
        if self.source.source_kind not in {"live", "fixture"}:
            raise ValueError("flight offer requires live or fixture source provenance")
        return self


class StayProfileRules(PricingModel):
    rules_version: str
    profile: Literal["economy", "standard", "comfort"]
    minimum_rating: Decimal = Field(ge=0, le=10)
    minimum_review_count: int = Field(ge=0)
    maximum_distance_km: Decimal = Field(gt=0)
    require_private_room: bool
    allow_shared_bathroom: bool
    require_flexible_cancellation: bool
    require_preferred_area: bool = False


class StayOffer(PricingModel):
    provider: str = Field(min_length=1, max_length=128)
    offer_id: str = Field(min_length=1, max_length=256)
    property_id: str = Field(min_length=1, max_length=256)
    product_id: str = Field(min_length=1, max_length=256)
    scenario_id: str = Field(min_length=8, max_length=64)
    checkin: date
    checkout: date
    adults: int = Field(ge=1, le=9)
    children: int = Field(default=0, ge=0, le=8)
    rooms: int = Field(ge=1, le=5)
    total_rub: Decimal = Field(gt=0)
    mandatory_excluded_rub: Decimal = Field(default=Decimal(0), ge=0)
    extra_local_transport_rub: Decimal = Field(default=Decimal(0), ge=0)
    covers_full_stay: bool
    covers_full_party: bool
    mandatory_charges_complete: bool
    private_room: bool
    dorm: bool
    shared_bathroom: bool
    in_preferred_area: bool | None = None
    rating: Decimal | None = Field(default=None, ge=0, le=10)
    review_count: int | None = Field(default=None, ge=0)
    distance_center_km: Decimal = Field(ge=0)
    cancellation: Literal["flexible", "nonrefundable", "unknown"]
    source: SourceRef

    @model_validator(mode="after")
    def stay_offer_is_consistent(self) -> StayOffer:
        if self.checkout <= self.checkin:
            raise ValueError("stay checkout must follow checkin")
        if self.dorm and self.private_room:
            raise ValueError("dorm cannot be a private room")
        if self.source.source_kind not in {"live", "fixture"}:
            raise ValueError("stay offer requires live or fixture source provenance")
        return self


class PriceTriple(PricingModel):
    low: Decimal = Field(ge=0)
    average: Decimal = Field(ge=0)
    high: Decimal = Field(ge=0)

    @model_validator(mode="after")
    def prices_are_ordered(self) -> PriceTriple:
        if not self.low <= self.average <= self.high:
            raise ValueError("price triple must satisfy low <= average <= high")
        return self


class FoodPriceSet(PricingModel):
    dataset_version: str
    inexpensive_meal: PriceTriple
    fast_food_combo: PriceTriple
    water_small: PriceTriple
    cappuccino: PriceTriple | None = None
    grocery_daily_basket: PriceTriple
    sources: tuple[SourceRef, ...] = Field(min_length=1)


class ChildTransitFare(PricingModel):
    age_min: int = Field(ge=0, le=17)
    age_max: int = Field(ge=0, le=17)
    single_ride_rub: Decimal = Field(ge=0)
    day_pass_rub: Decimal | None = Field(default=None, ge=0)
    weekly_pass_rub: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def age_range_is_ordered(self) -> ChildTransitFare:
        if self.age_min > self.age_max:
            raise ValueError("child transit age_min must not exceed age_max")
        return self


class TransitFareSet(PricingModel):
    dataset_version: str
    adult_single_ride_rub: Decimal = Field(ge=0)
    adult_day_pass_rub: Decimal | None = Field(default=None, ge=0)
    adult_weekly_pass_rub: Decimal | None = Field(default=None, ge=0)
    child_fares: tuple[ChildTransitFare, ...] = ()
    sources: tuple[SourceRef, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def child_age_ranges_do_not_overlap(self) -> TransitFareSet:
        covered: set[int] = set()
        for fare in self.child_fares:
            ages = set(range(fare.age_min, fare.age_max + 1))
            if covered & ages:
                raise ValueError("child transit age ranges cannot overlap")
            covered.update(ages)
        return self


class EntryCharge(PricingModel):
    charge_id: str = Field(min_length=1, max_length=128)
    charge_type: Literal["visa", "eta", "tourist_tax", "entry_fee"]
    age_min: int | None = Field(default=None, ge=0)
    age_max: int | None = Field(default=None, ge=0)
    amount: Decimal = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    basis: Literal["per_person", "per_trip", "per_night", "percent_stay"]
    required: bool

    @model_validator(mode="after")
    def charge_is_consistent(self) -> EntryCharge:
        if self.age_min is not None and self.age_max is not None and self.age_min > self.age_max:
            raise ValueError("entry charge age_min must not exceed age_max")
        if self.basis == "percent_stay":
            if self.age_min is not None or self.age_max is not None:
                raise ValueError("percent_stay charge cannot use age bounds")
            if self.amount > 100:
                raise ValueError("percent_stay charge cannot exceed 100%")
        return self


class EntryChargeRegistry(PricingModel):
    registry_version: str
    citizenship_country: str = Field(pattern=r"^[A-Z]{2}$")
    destination_country: str = Field(pattern=r"^[A-Z]{2}$")
    review_status: Literal["confirmed", "stale", "needs_review", "unknown"]
    charges: tuple[EntryCharge, ...] = ()
    source: SourceRef


class CostComponent(PricingModel):
    scenario_id: str = Field(min_length=8, max_length=64)
    name: ComponentName
    amount: MoneyRange | None
    status: ComponentStatus
    included: tuple[str, ...] = ()
    excluded: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    sources: tuple[SourceRef, ...] = ()

    @model_validator(mode="after")
    def amount_matches_status(self) -> CostComponent:
        if self.status in {"missing", "unsupported"} and self.amount is not None:
            raise ValueError("missing or unsupported components cannot carry an amount")
        if self.status in {"available", "partial", "stale"} and self.amount is None:
            raise ValueError("priced component status requires an amount")
        if self.amount is not None and not self.sources:
            raise ValueError("priced components require source provenance")
        return self


class ScenarioPrice(PricingModel):
    scenario: DateScenario
    components: tuple[CostComponent, ...]
    total: MoneyRange | None
    missing_components: tuple[ComponentName, ...] = ()
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    @model_validator(mode="after")
    def components_match_scenario(self) -> ScenarioPrice:
        names = [component.name for component in self.components]
        if len(names) != len(set(names)):
            raise ValueError("scenario cannot contain duplicate components")
        if any(component.scenario_id != self.scenario.scenario_id for component in self.components):
            raise ValueError("component scenario_id must match scenario")
        return self


class TripPriceEstimate(PricingModel):
    pricing_snapshot_id: str = Field(min_length=8, max_length=64)
    pricing_version: str
    request_hash: str = Field(min_length=8, max_length=64)
    scenario_count_generated: int = Field(ge=1)
    scenario_count_priced: int = Field(ge=0)
    total: MoneyRange | None
    components: tuple[CostComponent, ...]
    selected_scenario_id: str | None = None
    scenarios: tuple[ScenarioPrice, ...] = ()
    confidence: Literal["high", "medium", "low", "insufficient"]
    calculated_at: datetime
    valid_until: datetime | None = None
    assumptions: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    missing_components: tuple[ComponentName, ...] = ()

    @model_validator(mode="after")
    def snapshot_is_consistent(self) -> TripPriceEstimate:
        if self.calculated_at.tzinfo is None:
            raise ValueError("calculated_at must be timezone-aware")
        if self.scenario_count_priced != len(self.scenarios):
            raise ValueError("scenario_count_priced must match scenarios")
        if self.total is None and self.confidence != "insufficient":
            raise ValueError("snapshot without total must have insufficient confidence")
        if self.selected_scenario_id is not None and self.selected_scenario_id not in {
            item.scenario.scenario_id for item in self.scenarios
        }:
            raise ValueError("selected scenario must be present in snapshot")
        return self
