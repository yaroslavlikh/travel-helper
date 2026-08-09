from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from app.pricing.config import CachedFlightConfig
from app.pricing.errors import CachedFlightProviderError
from app.pricing.models import (
    DateScenario,
    FlightPriceSignal,
    PricingRequest,
    ScenarioBatch,
    SourceRef,
)
from app.pricing.providers.aviasales_data import (
    AVIASALES_PRICES_URL,
    AviasalesDataProvider,
    normalize_aviasales_signals,
)
from app.pricing.scenario_generation import generate_date_scenarios
from app.pricing.scenario_selection import select_scenarios_for_full_pricing

NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _request(**updates: object) -> PricingRequest:
    values: dict[str, object] = {
        "request_id": "request-flight-signal",
        "origin_city_id": "moscow",
        "origin_iata": ("MOW",),
        "destination_id": "istanbul",
        "destination_iata": ("IST",),
        "date_mode": "month",
        "month": "2026-09",
        "nights_min": 7,
        "nights_max": 7,
        "adults": 2,
        "rooms": 1,
    }
    values.update(updates)
    return PricingRequest.model_validate(values)


def _item(
    *,
    outbound: str = "2026-09-12",
    return_date: str = "2026-09-19",
    price: object = 30_000,
    expires_at: str = "2026-07-29T12:00:00Z",
    actual: bool = True,
) -> dict[str, object]:
    return {
        "origin": "MOW",
        "destination": "IST",
        "departure_at": outbound,
        "return_at": return_date,
        "price": price,
        "transfers": 1,
        "return_transfers": 2,
        "airline": "TK",
        "duration": 300,
        "found_at": "2026-07-28T10:00:00Z",
        "expires_at": expires_at,
        "actual": actual,
        "link": "/MOW1209IST1909",
    }


def test_cached_flight_signal_is_never_usable_as_trip_total() -> None:
    batch = generate_date_scenarios(_request())

    signals = normalize_aviasales_signals(
        [_item()],
        batch=batch,
        request=_request(),
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert len(signals) == 1
    assert signals[0].amount_rub == Decimal("30000")
    assert signals[0].source.source_kind == "cached"
    assert signals[0].price_basis == "cached_unknown_party"
    assert signals[0].usable_for_total is False


def test_cached_signal_accepts_documented_response_without_source_timestamps() -> None:
    request = _request(
        date_mode="exact",
        month=None,
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 19),
    )
    item = {
        "origin": "MOW",
        "destination": "IST",
        "departure_at": "2026-09-12T09:40:00+03:00",
        "return_at": "2026-09-19T17:15:00+03:00",
        "price": 30_000,
        "transfers": 1,
        "return_transfers": 2,
        "airline": "TK",
        "duration": 300,
        "link": "/MOW1209IST1909",
    }

    signals = normalize_aviasales_signals(
        [item],
        batch=generate_date_scenarios(request),
        request=request,
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert len(signals) == 1
    assert signals[0].found_at is None
    assert signals[0].expires_at is None
    assert signals[0].age_hours is None
    assert signals[0].confidence == 0.35
    assert signals[0].source.observed_at == NOW
    assert signals[0].source.valid_until is None


@pytest.mark.parametrize(
    "item",
    [
        _item(outbound="2026-08-12", return_date="2026-08-19"),
        _item(price=0),
        _item(price=-1),
        _item(expires_at="2026-07-28T11:59:00Z"),
        _item(actual=False),
        {**_item(), "origin": "MOSCOW"},
        {**_item(), "origin": "LED"},
    ],
)
def test_cached_signal_rejects_wrong_dates_expired_or_malformed_items(
    item: dict[str, object],
) -> None:
    signals = normalize_aviasales_signals(
        [item],
        batch=generate_date_scenarios(_request()),
        request=_request(),
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert signals == ()


def test_cached_signal_deduplicates_same_route_and_dates_by_price() -> None:
    batch = generate_date_scenarios(_request())

    signals = normalize_aviasales_signals(
        [_item(price=35_000), _item(price=29_000)],
        batch=batch,
        request=_request(),
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert [signal.amount_rub for signal in signals] == [Decimal("29000")]


def test_cached_month_signal_is_not_limited_to_internal_date_samples() -> None:
    request = _request()
    batch = ScenarioBatch(
        generated_count=30,
        scenarios=(
            DateScenario(
                scenario_id="sampled-date",
                outbound_date=date(2026, 9, 1),
                return_date=date(2026, 9, 8),
                nights=7,
            ),
        ),
        sampling_applied=True,
    )

    signals = normalize_aviasales_signals(
        [_item(outbound="2026-09-27", return_date="2026-10-04")],
        batch=batch,
        request=request,
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert len(signals) == 1
    assert signals[0].outbound_date == date(2026, 9, 27)
    assert signals[0].scenario_id != "sampled-date"


def test_cached_signal_keeps_a_long_provider_link_without_rejecting_the_price() -> None:
    signals = normalize_aviasales_signals(
        [{**_item(), "link": "/" + "x" * 400}],
        batch=generate_date_scenarios(_request()),
        request=_request(),
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    assert len(signals) == 1
    assert signals[0].provider_url is not None
    assert len(signals[0].source.raw_reference_id or "") == 256


@pytest.mark.asyncio
async def test_aviasales_adapter_uses_header_and_filters_hard_flight_limits() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"success": True, "currency": "rub", "data": [_item()]},
            request=request,
        )

    request = _request(
        date_mode="exact",
        month=None,
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 19),
        max_stops=1,
        max_flight_minutes=360,
    )
    batch = generate_date_scenarios(request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AviasalesDataProvider(client, SecretStr("token-value"))
        signals = await provider.search(request, batch, now=NOW)

    assert len(signals) == 1
    assert requests[0].headers["X-Access-Token"] == "token-value"
    assert "token" not in requests[0].url.params
    assert requests[0].url.params["departure_at"] == "2026-09-12"
    assert requests[0].url.params["return_at"] == "2026-09-19"
    assert requests[0].url.params["market"] == "ru"
    assert requests[0].url.params["currency"] == "rub"
    assert requests[0].url.params["one_way"] == "false"

    blocked = request.model_copy(update={"max_stops": 0})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AviasalesDataProvider(client, SecretStr("token-value"))
        assert await provider.search(blocked, batch, now=NOW) == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "payload"),
    [
        (429, {"success": False, "data": []}),
        (200, {"success": False, "data": []}),
        (200, {"success": True, "currency": "usd", "data": []}),
        (200, {"success": True, "currency": "rub", "data": {}}),
    ],
)
async def test_aviasales_adapter_rejects_provider_failures(
    status: int, payload: dict[str, object]
) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, request=request)

    request = _request(
        date_mode="exact",
        month=None,
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 19),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AviasalesDataProvider(client, SecretStr("token-value"))
        with pytest.raises(CachedFlightProviderError):
            await provider.search(request, generate_date_scenarios(request), now=NOW)


def _signal(day: int, price: int) -> FlightPriceSignal:
    outbound = date(2026, 9, day)
    return_date = outbound + timedelta(days=7)
    scenario = next(
        scenario
        for scenario in generate_date_scenarios(_request()).scenarios
        if scenario.outbound_date == outbound
    )
    source = SourceRef(
        source_id=f"source-{day}",
        provider="aviasales-data",
        source_kind="cached",
        observed_at=NOW,
        valid_until=NOW + timedelta(days=1),
    )
    return FlightPriceSignal(
        signal_id=f"signal-{day:02d}",
        scenario_id=scenario.scenario_id,
        origin_iata="MOW",
        destination_iata="IST",
        outbound_date=outbound,
        return_date=return_date,
        amount_rub=price,
        found_at=NOW,
        expires_at=NOW + timedelta(days=1),
        source=source,
    )


def test_month_selection_keeps_cheap_and_early_middle_late_coverage() -> None:
    batch = generate_date_scenarios(_request())
    signals = tuple(
        _signal(day, price)
        for day, price in [
            (2, 50_000),
            (5, 51_000),
            (12, 20_000),
            (13, 21_000),
            (14, 22_000),
            (15, 23_000),
            (16, 24_000),
            (17, 25_000),
            (25, 52_000),
            (28, 53_000),
        ]
    )

    selected = select_scenarios_for_full_pricing(batch, signals)
    selected_days = {scenario.outbound_date.day for scenario in selected}

    assert {12, 13, 14, 15, 16, 17}.issubset(selected_days)
    assert {2, 5}.issubset(selected_days)
    assert {25, 28}.issubset(selected_days)
    assert len(selected) <= 12


def test_cached_signal_keeps_provider_metadata_and_derived_confidence() -> None:
    signals = normalize_aviasales_signals(
        [_item()],
        batch=generate_date_scenarios(_request()),
        request=_request(),
        now=NOW,
        source_url=AVIASALES_PRICES_URL,
    )

    signal = signals[0]
    assert signal.currency == "RUB"
    assert signal.airline == "TK"
    assert signal.return_stops == 2
    assert signal.provider_url == "https://www.aviasales.ru/MOW1209IST1909"
    assert signal.fetched_at == NOW
    assert signal.age_hours == 2
    assert signal.confidence == 0.65


@pytest.mark.asyncio
async def test_aviasales_adapter_caches_empty_and_retries_only_server_errors() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(503, json={"success": False}, request=request)
        return httpx.Response(
            200, json={"success": True, "currency": "rub", "data": []}, request=request
        )

    request = _request(
        date_mode="exact",
        month=None,
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 19),
    )
    config = CachedFlightConfig(
        max_retries=1,
        retry_backoff_seconds=0,
        min_request_interval_seconds=0,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AviasalesDataProvider(client, SecretStr("token-value"), config=config)
        batch = generate_date_scenarios(request)
        assert await provider.search(request, batch, now=NOW) == ()
        assert await provider.search(request, batch, now=NOW + timedelta(minutes=5)) == ()

    assert calls == 2


@pytest.mark.asyncio
async def test_aviasales_adapter_does_not_retry_client_errors_or_log_token(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401, json={"success": False}, request=request)

    request = _request(
        date_mode="exact",
        month=None,
        outbound_date=date(2026, 9, 12),
        return_date=date(2026, 9, 19),
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = AviasalesDataProvider(
            client,
            SecretStr("private-token-value"),
            config=CachedFlightConfig(max_retries=2, min_request_interval_seconds=0),
        )
        with pytest.raises(CachedFlightProviderError):
            await provider.search(request, generate_date_scenarios(request), now=NOW)

    assert calls == 1
    assert "private-token-value" not in caplog.text
