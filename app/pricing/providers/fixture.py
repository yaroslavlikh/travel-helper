"""Exact-request fixture adapters for tests and explicitly marked staging mode."""

from __future__ import annotations

from app.pricing.models import DateScenario, FlightOffer, PricingRequest, StayOffer


class FixtureFlightPriceProvider:
    provider_name = "fixture"

    def __init__(self, offers: tuple[FlightOffer, ...] = ()) -> None:
        self._offers = offers

    async def search(
        self, request: PricingRequest, scenario: DateScenario
    ) -> tuple[FlightOffer, ...]:
        return tuple(
            offer
            for offer in self._offers
            if offer.source.source_kind == "fixture"
            and offer.scenario_id == scenario.scenario_id
            and offer.origin_iata in request.origin_iata
            and offer.destination_iata in request.destination_iata
            and offer.adults == request.adults
            and offer.children == len(request.children_ages)
            and offer.infants == request.infants
            and offer.outbound_departure.date() == scenario.outbound_date
            and offer.return_arrival.date() == scenario.return_date
        )


class FixtureStayPriceProvider:
    provider_name = "fixture"

    def __init__(self, offers: tuple[StayOffer, ...] = ()) -> None:
        self._offers = offers

    async def search(
        self, request: PricingRequest, scenario: DateScenario
    ) -> tuple[StayOffer, ...]:
        return tuple(
            offer
            for offer in self._offers
            if offer.source.source_kind == "fixture"
            and offer.scenario_id == scenario.scenario_id
            and offer.checkin == scenario.outbound_date
            and offer.checkout == scenario.return_date
            and offer.adults == request.adults
            and offer.children == len(request.children_ages)
            and offer.rooms == request.rooms
        )
