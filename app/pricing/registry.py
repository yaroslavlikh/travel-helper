"""Provider selection and safe operational status for deterministic pricing."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import Settings
from app.pricing.ports.flights import CachedFlightDiscovery, FlightPriceProvider
from app.pricing.ports.stays import StayPriceProvider
from app.pricing.providers.aviasales_data import AviasalesDataProvider
from app.pricing.providers.fixture import FixtureFlightPriceProvider, FixtureStayPriceProvider
from app.pricing.providers.unavailable import (
    UnavailableCachedFlightDiscovery,
    UnavailableFlightPriceProvider,
    UnavailableStayPriceProvider,
)

ProviderMode = Literal["disabled", "fixture", "cached", "live"]
ProviderState = Literal["ready", "disabled", "fixture", "missing_credentials", "not_implemented"]


@dataclass(frozen=True, slots=True)
class PricingProviderStatus:
    name: Literal["flight_pricing", "flight_cached_discovery", "stay_pricing"]
    mode: ProviderMode
    status: ProviderState
    reason: str


@dataclass(frozen=True, slots=True)
class PricingProviderRegistry:
    flight: FlightPriceProvider
    cached_flight: CachedFlightDiscovery
    stay: StayPriceProvider
    flight_status: PricingProviderStatus
    cached_flight_status: PricingProviderStatus
    stay_status: PricingProviderStatus

    @property
    def is_ready(self) -> bool:
        return self.flight_status.status == "ready" and self.stay_status.status == "ready"

    def public_statuses(
        self,
    ) -> tuple[PricingProviderStatus, PricingProviderStatus, PricingProviderStatus]:
        return self.flight_status, self.cached_flight_status, self.stay_status


def create_pricing_provider_registry(
    settings: Settings, http_client: httpx.AsyncClient | None = None
) -> PricingProviderRegistry:
    flight, flight_status = _flight_provider(settings)
    cached_flight, cached_flight_status = _cached_flight_provider(settings, http_client)
    stay, stay_status = _stay_provider(settings)
    return PricingProviderRegistry(
        flight=flight,
        cached_flight=cached_flight,
        stay=stay,
        flight_status=flight_status,
        cached_flight_status=cached_flight_status,
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


def _cached_flight_provider(
    settings: Settings, http_client: httpx.AsyncClient | None
) -> tuple[CachedFlightDiscovery, PricingProviderStatus]:
    if settings.flight_provider_mode != "cached" or not settings.pricing_cached_enabled:
        return UnavailableCachedFlightDiscovery("disabled"), PricingProviderStatus(
            "flight_cached_discovery",
            "disabled",
            "disabled",
            "Cached flight discovery is disabled.",
        )
    if not settings.travelpayouts_is_configured:
        return UnavailableCachedFlightDiscovery("missing_credentials"), PricingProviderStatus(
            "flight_cached_discovery",
            "cached",
            "missing_credentials",
            "Travelpayouts API token is missing.",
        )
    if http_client is None:
        raise ValueError("cached flight provider requires an application HTTP client")
    assert settings.travelpayouts_api_token is not None
    return AviasalesDataProvider(
        http_client, settings.travelpayouts_api_token
    ), PricingProviderStatus(
        "flight_cached_discovery",
        "cached",
        "ready",
        "Aviasales cached flight discovery is configured; it is not live pricing.",
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
