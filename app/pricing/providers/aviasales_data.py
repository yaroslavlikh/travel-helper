"""Aviasales Data API adapter for cached date discovery, never live pricing."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any

import httpx
from pydantic import SecretStr, ValidationError

from app.pricing.config import CACHED_FLIGHT_CONFIG, CachedFlightConfig
from app.pricing.errors import CachedFlightProviderError
from app.pricing.models import (
    FlightPriceSignal,
    PricingRequest,
    ScenarioBatch,
    SourceRef,
)

AVIASALES_PRICES_URL = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates"


class AviasalesDataProvider:
    """Read cached route/date observations using an application-owned client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: SecretStr,
        *,
        config: CachedFlightConfig = CACHED_FLIGHT_CONFIG,
    ) -> None:
        if not token.get_secret_value():
            raise ValueError("Aviasales Data token cannot be empty")
        self._client = client
        self._token = token
        self._config = config

    async def search(
        self,
        request: PricingRequest,
        batch: ScenarioBatch,
        *,
        now: datetime,
    ) -> tuple[FlightPriceSignal, ...]:
        if now.tzinfo is None:
            raise CachedFlightProviderError("flight discovery clock must be timezone-aware")
        if len(request.origin_iata) * len(request.destination_iata) > self._config.max_route_pairs:
            raise CachedFlightProviderError("too many IATA route pairs for cached discovery")
        raw_items: list[dict[str, Any]] = []
        for origin in request.origin_iata:
            for destination in request.destination_iata:
                for departure_at, return_at in _query_periods(request, batch):
                    payload = await self._request_pair(origin, destination, departure_at, return_at)
                    raw_items.extend(payload)
        signals = normalize_aviasales_signals(
            raw_items,
            batch=batch,
            request=request,
            now=now,
            source_url=AVIASALES_PRICES_URL,
        )
        return tuple(
            signal
            for signal in signals
            if (
                request.max_stops is None
                or (signal.stops is not None and signal.stops <= request.max_stops)
            )
            and (
                request.max_flight_minutes is None
                or (
                    signal.duration_minutes is not None
                    and signal.duration_minutes <= request.max_flight_minutes
                )
            )
        )

    async def _request_pair(
        self, origin: str, destination: str, departure_at: str, return_at: str
    ) -> list[dict[str, Any]]:
        params = {
            "origin": origin,
            "destination": destination,
            "departure_at": departure_at,
            "return_at": return_at,
            "one_way": "false",
            "direct": "false",
            "currency": "rub",
            "sorting": "price",
            "limit": str(self._config.page_limit),
            "page": "1",
        }
        try:
            response = await self._client.get(
                AVIASALES_PRICES_URL,
                params=params,
                headers={
                    "X-Access-Token": self._token.get_secret_value(),
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise CachedFlightProviderError("Aviasales Data request failed") from error
        if len(response.content) > self._config.max_response_bytes:
            raise CachedFlightProviderError("Aviasales Data response is too large")
        try:
            payload = response.json()
        except ValueError as error:
            raise CachedFlightProviderError("Aviasales Data returned malformed JSON") from error
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise CachedFlightProviderError("Aviasales Data returned an unsuccessful response")
        currency = payload.get("currency")
        if currency is not None and (not isinstance(currency, str) or currency.casefold() != "rub"):
            raise CachedFlightProviderError("Aviasales Data returned an unsupported currency")
        data = payload.get("data")
        if not isinstance(data, list):
            raise CachedFlightProviderError("Aviasales Data response has invalid data")
        return [item for item in data if isinstance(item, dict)]


def normalize_aviasales_signals(
    items: list[dict[str, Any]],
    *,
    batch: ScenarioBatch,
    request: PricingRequest,
    now: datetime,
    source_url: str,
) -> tuple[FlightPriceSignal, ...]:
    """Normalize only exact generated date pairs and discard expired/malformed cache entries."""

    scenarios = {
        (scenario.outbound_date, scenario.return_date): scenario for scenario in batch.scenarios
    }
    normalized: dict[tuple[str, str, date, date], FlightPriceSignal] = {}
    for item in items:
        try:
            outbound = _as_date(item.get("departure_at"))
            return_date = _as_date(item.get("return_at"))
            scenario = scenarios[(outbound, return_date)]
            origin = _iata(item.get("origin"))
            destination = _iata(item.get("destination"))
            if origin not in request.origin_iata or destination not in request.destination_iata:
                continue
            amount = Decimal(str(item.get("price")))
            found_at = _as_datetime(item.get("found_at"))
            expires_at = _as_datetime(item.get("expires_at"))
            if expires_at <= now or found_at > now or amount <= 0 or item.get("actual") is not True:
                continue
            stops_raw = item.get("transfers")
            stops = int(stops_raw) if stops_raw is not None else None
            if stops is not None and stops < 0:
                continue
            duration_raw = item.get("duration")
            duration = int(duration_raw) if duration_raw is not None else None
            if duration is not None and duration <= 0:
                continue
            signal_key = f"{origin}|{destination}|{outbound}|{return_date}|{amount}|{found_at}"
            source = SourceRef(
                source_id=f"aviasales-cache-{sha256(signal_key.encode()).hexdigest()[:20]}",
                provider="aviasales-data",
                source_kind="cached",
                observed_at=found_at,
                valid_until=expires_at,
                source_url=source_url,
                raw_reference_id=str(item.get("link") or "") or None,
            )
            signal = FlightPriceSignal(
                signal_id=f"fps_{sha256(signal_key.encode()).hexdigest()[:20]}",
                scenario_id=scenario.scenario_id,
                origin_iata=origin,
                destination_iata=destination,
                outbound_date=outbound,
                return_date=return_date,
                amount_rub=amount,
                stops=stops,
                duration_minutes=duration,
                found_at=found_at,
                expires_at=expires_at,
                source=source,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            InvalidOperation,
            ValidationError,
        ):
            continue
        key = (origin, destination, outbound, return_date)
        current = normalized.get(key)
        if current is None or signal.amount_rub < current.amount_rub:
            normalized[key] = signal
    return tuple(
        sorted(
            normalized.values(),
            key=lambda signal: (
                signal.outbound_date,
                signal.return_date,
                signal.amount_rub,
                signal.origin_iata,
                signal.destination_iata,
            ),
        )
    )


def _query_periods(request: PricingRequest, batch: ScenarioBatch) -> tuple[tuple[str, str], ...]:
    if request.date_mode == "exact":
        assert request.outbound_date is not None and request.return_date is not None
        return ((request.outbound_date.isoformat(), request.return_date.isoformat()),)
    return tuple(
        sorted(
            {
                (
                    scenario.outbound_date.strftime("%Y-%m"),
                    scenario.return_date.strftime("%Y-%m"),
                )
                for scenario in batch.scenarios
            }
        )
    )


def _as_date(value: object) -> date:
    if not isinstance(value, str):
        raise ValueError("date is missing")
    return date.fromisoformat(value[:10])


def _as_datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _iata(value: object) -> str:
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha():
        raise ValueError("invalid IATA")
    return value.upper()
