from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from app.pricing.config import FxConfig
from app.pricing.errors import FxProviderError
from app.pricing.models import FxRate, FxRateTable, SourceRef
from app.pricing.normalization.money import convert_to_rub
from app.pricing.providers.cbr_fx import CachedFxProvider, CbrFxProvider, parse_cbr_rates

CBR_XML = b"""<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="28.07.2026" name="Foreign Currency Market">
  <Valute ID="R01235">
    <NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal>
    <Name>US Dollar</Name><Value>78,5012</Value>
  </Valute>
  <Valute ID="R01375">
    <NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>10</Nominal>
    <Name>Yuan Renminbi</Name><Value>109,8765</Value>
  </Valute>
</ValCurs>"""
NOW = datetime(2026, 7, 28, 12, tzinfo=UTC)


def _table(*, fetched_at: datetime = NOW) -> FxRateTable:
    source = SourceRef(
        source_id="cbr-2026-07-28",
        provider="cbr",
        source_kind="live",
        observed_at=fetched_at,
        valid_until=fetched_at + timedelta(days=1),
    )
    return FxRateTable(
        table_version="cbr-fx-v1",
        effective_date=date(2026, 7, 28),
        fetched_at=fetched_at,
        rates=(
            FxRate(char_code="USD", nominal=1, value_rub=Decimal("78.5012")),
            FxRate(char_code="CNY", nominal=10, value_rub=Decimal("109.8765")),
        ),
        source=source,
    )


def test_cbr_parser_preserves_decimal_and_nominal() -> None:
    rates = parse_cbr_rates(
        CBR_XML,
        fetched_at=NOW,
        source_url="https://www.cbr.ru/scripts/XML_daily.asp",
    )

    assert rates.effective_date == date(2026, 7, 28)
    assert rates.rate_for("CNY").rub_per_unit == Decimal("10.98765")
    assert convert_to_rub(Decimal("100"), "CNY", rates) == Decimal("1098.77")
    assert convert_to_rub(Decimal("100.125"), "RUB", rates) == Decimal("100.13")


@pytest.mark.parametrize(
    "payload",
    [
        b"<not-xml",
        b'<ValCurs Date="28.07.2026"></ValCurs>',
        (
            b'<ValCurs Date="bad"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal>'
            b"<Value>1</Value></Valute></ValCurs>"
        ),
        (
            b'<ValCurs Date="28.07.2026"><Valute><CharCode>USD</CharCode><Nominal>0</Nominal>'
            b"<Value>1</Value></Valute></ValCurs>"
        ),
        (
            b'<ValCurs Date="28.07.2026"><Valute><CharCode>USD</CharCode><Nominal>1</Nominal>'
            b"<Value>-1</Value></Valute></ValCurs>"
        ),
    ],
)
def test_cbr_parser_rejects_malformed_or_nonpositive_rates(payload: bytes) -> None:
    with pytest.raises(FxProviderError):
        parse_cbr_rates(payload, fetched_at=NOW, source_url="https://www.cbr.ru/")


@pytest.mark.asyncio
async def test_cbr_adapter_passes_official_date_parameter() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=CBR_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = CbrFxProvider(client, clock=lambda: NOW)
        rates = await provider.get_rates(date(2026, 7, 28))

    assert rates.rate_for("USD").value_rub == Decimal("78.5012")
    assert requests[0].url.params["date_req"] == "28/07/2026"


@pytest.mark.asyncio
async def test_cbr_adapter_maps_http_and_size_failures() -> None:
    async def unavailable(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(unavailable)) as client:
        with pytest.raises(FxProviderError, match="request failed"):
            await CbrFxProvider(client, clock=lambda: NOW).get_rates()

    async def oversized(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=CBR_XML, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(oversized)) as client:
        provider = CbrFxProvider(
            client,
            clock=lambda: NOW,
            config=FxConfig(max_response_bytes=10),
        )
        with pytest.raises(FxProviderError, match="too large"):
            await provider.get_rates()


class _SequenceProvider:
    def __init__(self, results: list[FxRateTable | Exception]) -> None:
        self.results = results
        self.calls = 0

    async def get_rates(self, on_date: date | None = None) -> FxRateTable:
        result = self.results[self.calls]
        self.calls += 1
        if isinstance(result, Exception):
            raise result
        return result


@pytest.mark.asyncio
async def test_fx_cache_uses_valid_cache_then_bounded_stale_fallback() -> None:
    clock = [NOW]
    upstream = _SequenceProvider([_table(), FxProviderError("offline")])
    cached = CachedFxProvider(upstream, clock=lambda: clock[0])

    first = await cached.get_rates()
    clock[0] = NOW + timedelta(hours=12)
    valid_cache = await cached.get_rates()
    clock[0] = NOW + timedelta(hours=25)
    stale_fallback = await cached.get_rates()

    assert first.source.source_kind == "live"
    assert valid_cache.source.source_kind == "cached"
    assert stale_fallback.source.source_kind == "cached"
    assert upstream.calls == 2
    assert "72 часов" in stale_fallback.warnings[0]


@pytest.mark.asyncio
async def test_fx_cache_does_not_use_data_older_than_72_hours() -> None:
    clock = [NOW]
    upstream = _SequenceProvider([_table(), FxProviderError("offline")])
    cached = CachedFxProvider(upstream, clock=lambda: clock[0])
    await cached.get_rates()
    clock[0] = NOW + timedelta(hours=73)

    with pytest.raises(FxProviderError, match="offline"):
        await cached.get_rates()


def test_currency_conversion_rejects_missing_or_negative_values() -> None:
    rates = _table()

    with pytest.raises(KeyError, match="unsupported currency"):
        convert_to_rub(Decimal("10"), "EUR", rates)
    with pytest.raises(ValueError, match="negative"):
        convert_to_rub(Decimal("-1"), "USD", rates)
