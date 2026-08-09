"""Aviasales Data API adapter for cached date discovery, never live pricing."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Any
from urllib.parse import urljoin

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
AVIASALES_WEB_URL = "https://www.aviasales.ru"
LOGGER = logging.getLogger(__name__)


class AviasalesDataProvider:
    """Read cached route/date observations using an application-owned client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        token: SecretStr,
        *,
        config: CachedFlightConfig = CACHED_FLIGHT_CONFIG,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token.get_secret_value():
            raise ValueError("Aviasales Data token cannot be empty")
        self._client = client
        self._token = token
        self._config = config
        self._sleeper = sleeper
        self._monotonic = monotonic
        self._cache: dict[tuple[object, ...], tuple[datetime, tuple[FlightPriceSignal, ...]]] = {}
        self._rate_lock = asyncio.Lock()
        self._last_request_at: float | None = None

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
        cache_key = (
            request.origin_iata,
            request.destination_iata,
            tuple((item.outbound_date, item.return_date) for item in batch.scenarios),
            request.max_stops,
            request.max_flight_minutes,
        )
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] <= timedelta(seconds=self._config.cache_ttl_seconds):
            return cached[1]
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
        result = tuple(
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
        self._cache[cache_key] = (now, result)
        return result

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
            "market": "ru",
            "currency": "rub",
            "sorting": "price",
            "limit": str(self._config.page_limit),
            "page": "1",
        }
        response = await self._get_with_retry(params)
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

    async def _get_with_retry(self, params: dict[str, str]) -> httpx.Response:
        attempts = self._config.max_retries + 1
        for attempt in range(attempts):
            await self._wait_for_rate_slot()
            try:
                response = await self._client.get(
                    AVIASALES_PRICES_URL,
                    params=params,
                    headers={
                        "X-Access-Token": self._token.get_secret_value(),
                        "Accept-Encoding": "gzip, deflate",
                    },
                    timeout=httpx.Timeout(self._config.timeout_seconds),
                )
            except httpx.TransportError as error:
                if attempt + 1 == attempts:
                    raise CachedFlightProviderError(
                        "Aviasales Data network request failed"
                    ) from error
                await self._retry_delay(attempt, "network")
                continue
            if response.status_code >= 500:
                if attempt + 1 == attempts:
                    raise CachedFlightProviderError("Aviasales Data server request failed")
                await self._retry_delay(attempt, f"http_{response.status_code}")
                continue
            if response.status_code >= 400:
                raise CachedFlightProviderError(
                    f"Aviasales Data request was rejected with status {response.status_code}"
                )
            return response
        raise AssertionError("retry loop must return or raise")

    async def _wait_for_rate_slot(self) -> None:
        async with self._rate_lock:
            now = self._monotonic()
            if self._last_request_at is not None:
                remaining = self._config.min_request_interval_seconds - (
                    now - self._last_request_at
                )
                if remaining > 0:
                    await self._sleeper(remaining)
            self._last_request_at = self._monotonic()

    async def _retry_delay(self, attempt: int, reason: str) -> None:
        delay = self._config.retry_backoff_seconds * (2**attempt)
        LOGGER.warning(
            "Aviasales Data request retry", extra={"attempt": attempt + 1, "reason": reason}
        )
        if delay:
            await self._sleeper(delay)


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
            found_at = _optional_datetime(item.get("found_at"))
            expires_at = _optional_datetime(item.get("expires_at"))
            if (
                (expires_at is not None and expires_at <= now)
                or (found_at is not None and found_at > now)
                or amount <= 0
                or item.get("actual") is False
            ):
                continue
            stops_raw = item.get("transfers")
            stops = int(stops_raw) if stops_raw is not None else None
            if stops is not None and stops < 0:
                continue
            duration_raw = item.get("duration")
            duration = int(duration_raw) if duration_raw is not None else None
            if duration is not None and duration <= 0:
                continue
            return_stops_raw = item.get("return_transfers")
            return_stops = int(return_stops_raw) if return_stops_raw is not None else None
            if return_stops is not None and return_stops < 0:
                continue
            airline = _airline(item.get("airline"))
            age_hours = (
                max(0, int((now - found_at).total_seconds() // 3600))
                if found_at is not None
                else None
            )
            signal_key = (
                f"{origin}|{destination}|{outbound}|{return_date}|{amount}|"
                f"{found_at or item.get('link') or 'unknown'}"
            )
            source = SourceRef(
                source_id=f"aviasales-cache-{sha256(signal_key.encode()).hexdigest()[:20]}",
                provider="aviasales-data",
                source_kind="cached",
                observed_at=found_at or now,
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
                airline=airline,
                stops=stops,
                return_stops=return_stops,
                duration_minutes=duration,
                found_at=found_at,
                expires_at=expires_at,
                fetched_at=now,
                age_hours=age_hours,
                confidence=_confidence_for_age(age_hours),
                provider_url=_provider_url(item.get("link")),
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


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("timestamp is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _airline(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("airline must be a string")
    normalized = value.strip().upper()
    if not 2 <= len(normalized) <= 8:
        raise ValueError("airline has invalid length")
    return normalized


def _provider_url(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("/"):
        return None
    return urljoin(AVIASALES_WEB_URL, value)


def _confidence_for_age(age_hours: int | None) -> float:
    if age_hours is None:
        return 0.35
    if age_hours <= 12:
        return 0.65
    if age_hours <= 48:
        return 0.45
    return 0.25


def _iata(value: object) -> str:
    if not isinstance(value, str) or len(value) != 3 or not value.isalpha():
        raise ValueError("invalid IATA")
    return value.upper()
