"""Provider selection and safe operational status for deterministic pricing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.pricing.ports.flights import FlightPriceProvider
from app.pricing.ports.stays import StayPriceProvider
from app.pricing.providers.fixture import FixtureFlightPriceProvider, FixtureStayPriceProvider
from app.pricing.providers.unavailable import (
    UnavailableFlightPriceProvider,
    UnavailableStayPriceProvider,
)

ProviderMode = Literal["disabled", "fixture", "cached", "live"]
ProviderState = Literal["ready", "disabled", "fixture", "missing_credentials", "not_implemented"]


@dataclass(frozen=True, slots=True)
class PricingProviderStatus:
    name: Literal["flight_pricing", "stay_pricing"]
    mode: ProviderMode
    status: ProviderState
    reason: str


@dataclass(frozen=True, slots=True)
class PricingProviderRegistry:
    flight: FlightPriceProvider
    stay: StayPriceProvider
    flight_status: PricingProviderStatus
    stay_status: PricingProviderStatus

    @property
    def is_ready(self) -> bool:
        return all(item.status == "ready" for item in self.public_statuses())

    def public_statuses(self) -> tuple[PricingProviderStatus, PricingProviderStatus]:
        return self.flight_status, self.stay_status


def create_pricing_provider_registry(settings: Settings) -> PricingProviderRegistry:
    flight, flight_status = _flight_provider(settings)
    stay, stay_status = _stay_provider(settings)
    return PricingProviderRegistry(
        flight=flight,
        stay=stay,
        flight_status=flight_status,
        stay_status=stay_status,
    )


def _flight_provider(settings: Settings) -> tuple[FlightPriceProvider, PricingProviderStatus]:
    mode = settings.flight_provider_mode
    if mode == "fixture":
        return FixtureFlightPriceProvider(), PricingProviderStatus(
            "flight_pricing",
            mode,
            "fixture",
            "Fixture offers are allowed only outside public production.",
        )
    if mode == "live" and not settings.amadeus_is_configured:
        reason = "Live flight provider credentials are missing."
        return UnavailableFlightPriceProvider("missing_credentials"), PricingProviderStatus(
            "flight_pricing", mode, "missing_credentials", reason
        )
    reason = "Live flight adapter is not connected."
    status: ProviderState = "disabled" if mode == "disabled" else "not_implemented"
    return UnavailableFlightPriceProvider(status), PricingProviderStatus(
        "flight_pricing", mode, status, reason
    )


def _stay_provider(settings: Settings) -> tuple[StayPriceProvider, PricingProviderStatus]:
    mode = settings.stay_provider_mode
    if mode == "fixture":
        return FixtureStayPriceProvider(), PricingProviderStatus(
            "stay_pricing",
            mode,
            "fixture",
            "Fixture offers are allowed only outside public production.",
        )
    if mode == "live" and not settings.booking_is_configured:
        reason = "Live stay provider credentials are missing."
        return UnavailableStayPriceProvider("missing_credentials"), PricingProviderStatus(
            "stay_pricing", mode, "missing_credentials", reason
        )
    reason = "Live stay adapter is not connected."
    status: ProviderState = "disabled" if mode == "disabled" else "not_implemented"
    return UnavailableStayPriceProvider(status), PricingProviderStatus(
        "stay_pricing", mode, status, reason
    )
