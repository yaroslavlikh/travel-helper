"""Immutable public contracts for deterministic trip pricing."""

from __future__ import annotations

import re
from datetime import date, datetime
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
SourceKind = Literal["live", "cached", "manual", "derived"]


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
