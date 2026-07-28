"""Bank of Russia XML rates with deterministic parsing and bounded stale fallback."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree import ElementTree

import httpx
from pydantic import ValidationError

from app.pricing.config import FX_CONFIG, FxConfig
from app.pricing.errors import FxProviderError
from app.pricing.models import FxRate, FxRateTable, SourceRef
from app.pricing.ports.fx import FxRateProvider

CBR_DAILY_URL = "https://www.cbr.ru/scripts/XML_daily.asp"


class CbrFxProvider:
    """Fetch official daily rates through the application-owned HTTP client."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        clock: Callable[[], datetime] | None = None,
        config: FxConfig = FX_CONFIG,
    ) -> None:
        self._client = client
        self._clock = clock or (lambda: datetime.now(UTC))
        self._config = config

    async def get_rates(self, on_date: date | None = None) -> FxRateTable:
        params = {"date_req": on_date.strftime("%d/%m/%Y")} if on_date else None
        try:
            response = await self._client.get(CBR_DAILY_URL, params=params)
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise FxProviderError("Bank of Russia FX request failed") from error
        if len(response.content) > self._config.max_response_bytes:
            raise FxProviderError("Bank of Russia FX response is too large")
        return parse_cbr_rates(
            response.content,
            fetched_at=self._clock(),
            source_url=str(response.request.url),
            config=self._config,
        )


class CachedFxProvider:
    """Small process-local cache with an explicit 72-hour failure ceiling."""

    def __init__(
        self,
        upstream: FxRateProvider,
        *,
        clock: Callable[[], datetime] | None = None,
        config: FxConfig = FX_CONFIG,
    ) -> None:
        self._upstream = upstream
        self._clock = clock or (lambda: datetime.now(UTC))
        self._config = config
        self._cache: dict[date | None, FxRateTable] = {}

    async def get_rates(self, on_date: date | None = None) -> FxRateTable:
        now = self._clock()
        cached = self._cache.get(on_date)
        if cached and now - cached.fetched_at <= timedelta(seconds=self._config.cache_ttl_seconds):
            return _as_cached(cached, "Курс получен из валидного локального кэша.")
        try:
            result = await self._upstream.get_rates(on_date)
        except FxProviderError:
            if cached and now - cached.fetched_at <= timedelta(
                seconds=self._config.stale_fallback_seconds
            ):
                return _as_cached(
                    cached,
                    "Источник курсов недоступен; использован последний курс не старше 72 часов.",
                )
            raise
        self._cache[on_date] = result
        return result


def parse_cbr_rates(
    payload: bytes,
    *,
    fetched_at: datetime,
    source_url: str,
    config: FxConfig = FX_CONFIG,
) -> FxRateTable:
    """Parse the documented CBR XML format without float arithmetic."""

    if fetched_at.tzinfo is None:
        raise FxProviderError("FX fetch timestamp must be timezone-aware")
    try:
        root = ElementTree.fromstring(payload)
        effective_date = datetime.strptime(root.attrib["Date"], "%d.%m.%Y").date()
        rates = [
            FxRate(
                char_code=_required_text(item, "CharCode").upper(),
                nominal=int(_required_text(item, "Nominal")),
                value_rub=Decimal(_required_text(item, "Value").replace(",", ".")),
            )
            for item in root.findall("Valute")
        ]
    except (
        ElementTree.ParseError,
        KeyError,
        ValueError,
        InvalidOperation,
        ValidationError,
    ) as error:
        raise FxProviderError("Bank of Russia returned malformed FX XML") from error
    if not rates:
        raise FxProviderError("Bank of Russia returned no FX rates")
    source = SourceRef(
        source_id=f"cbr-{effective_date.isoformat()}",
        provider="cbr",
        source_kind="live",
        observed_at=fetched_at,
        valid_until=fetched_at + timedelta(seconds=config.cache_ttl_seconds),
        source_url=source_url,
    )
    try:
        return FxRateTable(
            table_version=config.version,
            effective_date=effective_date,
            fetched_at=fetched_at,
            rates=tuple(sorted(rates, key=lambda rate: rate.char_code)),
            source=source,
        )
    except ValidationError as error:
        raise FxProviderError("Bank of Russia returned invalid FX rates") from error


def _required_text(parent: ElementTree.Element, tag: str) -> str:
    value = parent.findtext(tag)
    if value is None or not value.strip():
        raise ValueError(f"missing {tag}")
    return value.strip()


def _as_cached(table: FxRateTable, warning: str) -> FxRateTable:
    return table.model_copy(
        update={
            "source": table.source.model_copy(update={"source_kind": "cached"}),
            "warnings": tuple(dict.fromkeys((*table.warnings, warning))),
        }
    )
