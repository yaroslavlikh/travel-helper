# ADR-0019: Bank of Russia as the primary RUB FX source

- Status: accepted
- Date: 2026-07-28

## Context

Pricing inputs may arrive in foreign currencies. Float arithmetic, undocumented market feeds and a
blanket exchange-rate markup would make scenario totals irreproducible. The Bank of Russia publishes
documented daily XML rates with currency `Nominal` and an optional `date_req` parameter.

## Decision

Use the official Bank of Russia `XML_daily.asp` feed as the primary RUB conversion source. Parse
rates with `Decimal`; calculate `rub_per_unit = Value / Nominal`; and round converted amounts with
`ROUND_HALF_UP`.

The adapter receives the application-owned `httpx.AsyncClient`. A process-local cache is valid for
24 hours. If the source fails, a cached table no older than 72 hours may be returned with an explicit
warning and `cached` source kind. Older data and unsupported currencies fail explicitly.

Cross-rates for currencies absent from the CBR table are deferred until an official secondary
central-bank source is selected.

## Consequences

- No API key or new dependency is required.
- Provider HTTP failures never turn an unknown currency into a zero price.
- Production multi-process caching or persistence remains a later repository concern.
