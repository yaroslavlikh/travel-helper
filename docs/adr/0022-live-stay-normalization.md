# ADR-0022: Provider-neutral live stay normalization

- Status: accepted
- Date: 2026-07-28

## Context

Hotel APIs differ on whether a number is nightly, per room, before tax or the complete occupancy
total. Multiplying a provider total again or mixing unsuitable dorms into a standard profile creates
large systematic errors.

## Decision

Adapters normalize exact-date results into `StayOffer`. Each offer explicitly confirms full stay,
full party, room count and completeness of mandatory charges. Mandatory charges excluded from the
provider total and sourced extra local transport are added once; the provider total is never
multiplied by nights or rooms.

Destination/profile rules are typed input rather than hardcoded global assumptions. They control
rating, reviews, distance, preferred area, private room, shared bathroom and cancellation. Dorms
require an explicit request flag. Aggregation uses up to ten cheapest acceptable unique products,
removes a lower outlier below 60% of the basket median, and derives floor/expected/safe from that
basket.

The Booking Demand adapter and destination rules registry remain credential/data slices.
