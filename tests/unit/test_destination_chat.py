from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel

from app.domain.models import (
    DestinationChatModelReply,
    DestinationThreadMessage,
    TravelRequest,
)
from app.places.models import PlaceDescription, PlaceSearchResult, PlaceSource
from app.services.destination_chat import _description_excerpt, answer_destination_question
from app.services.model_gateway import DisabledModelGateway
from app.services.scoring import rank_demo_candidates


class DestinationGateway:
    provider_name = "fake"
    model_name = "fake-model"

    def __init__(self) -> None:
        self.prompt = ""

    async def generate_structured(
        self,
        *,
        operation: str,
        prompt: str,
        schema: type[BaseModel],
        metadata: dict[str, Any],
    ) -> BaseModel:
        assert operation == "answer_destination_question"
        assert schema is DestinationChatModelReply
        assert metadata["history_message_count"] == 1
        self.prompt = prompt
        return DestinationChatModelReply(
            answer="Для спокойного размещения рассмотрите районы из карточки.",
            quick_replies=["А что рядом?"],
        )

    async def aclose(self) -> None:
        return None


def trip_request() -> TravelRequest:
    return TravelRequest(
        raw_query="Из Москвы на море в августе на неделю, 180 тысяч на одного, за границу",
        origin_city="Москва",
        month=8,
        duration_nights_min=7,
        duration_nights_max=7,
        adults=1,
        budget_total_rub=180_000,
        destination_scope="international",
        sea_required=True,
    )


async def test_destination_answer_uses_bounded_card_and_history_context() -> None:
    request = trip_request()
    recommendation = rank_demo_candidates(request)[0]
    gateway = DestinationGateway()

    reply, warnings = await answer_destination_question(
        query="Где лучше остановиться?",
        trip_request=request,
        recommendation=recommendation,
        history=[DestinationThreadMessage(role="assistant", text="Обсудим этот вариант.")],
        gateway=gateway,  # type: ignore[arg-type]
        demo_mode=False,
    )

    assert reply.quick_replies == ["А что рядом?"]
    assert warnings == []
    assert recommendation.candidate.city_or_region in gateway.prompt
    assert "Обсудим этот вариант" in gateway.prompt


async def test_destination_answer_has_explicit_demo_fallback() -> None:
    request = trip_request()
    recommendation = rank_demo_candidates(request)[0]

    reply, warnings = await answer_destination_question(
        query="Где лучше жить?",
        trip_request=request,
        recommendation=recommendation,
        history=[],
        gateway=DisabledModelGateway("not configured"),
        demo_mode=True,
    )

    assert recommendation.candidate.city_or_region in reply.answer
    assert recommendation.candidate.stay_areas[0] in reply.answer
    assert warnings and "Локальный режим" in warnings[0]


async def test_destination_fallback_answers_a_visa_question_from_the_card() -> None:
    request = trip_request()
    recommendation = rank_demo_candidates(request)[0]

    reply, warnings = await answer_destination_question(
        query="Там нужна виза?",
        trip_request=request,
        recommendation=recommendation,
        history=[],
        gateway=DisabledModelGateway("not configured"),
        demo_mode=True,
    )

    assert recommendation.candidate.entry_requirements in reply.answer
    assert "официальном ресурсе" in reply.answer
    assert warnings and "Локальный режим" in warnings[0]


async def test_destination_answer_passes_canonical_pois_as_evidence_context() -> None:
    request = trip_request()
    recommendation = rank_demo_candidates(request)[0]
    gateway = DestinationGateway()
    poi = PlaceSearchResult(
        place_id="00000000-0000-0000-0000-000000000001",
        name="Айя-София",
        destination="istanbul",
        latitude=41.0086,
        longitude=28.9802,
        category="museum",
        tags=["culture"],
        source=PlaceSource(
            name="OpenStreetMap / Overpass",
            url="https://www.openstreetmap.org/",
            attribution="© OpenStreetMap contributors",
        ),
        description=PlaceDescription(
            text=(
                "Айя-София — пример подтверждённого описания, которое передаётся в контекст "
                "только вместе с источником и не используется для утверждений о режиме работы."
            ),
            language_code="ru",
            content_kind="overview",
            observed_at=datetime(2026, 7, 18, tzinfo=UTC),
            source=PlaceSource(
                name="Licensed Istanbul Guide",
                url="https://guide.example/aya-sophia",
                attribution="© Licensed Istanbul Guide",
                license="Direct partner permission",
            ),
        ),
        scores={"final": 0.8},
        reasons=["Совпало с тематикой запроса"],
        ranking_version="istanbul-hybrid-v1",
    )

    await answer_destination_question(
        query="Что посмотреть?",
        trip_request=request,
        recommendation=recommendation,
        history=[DestinationThreadMessage(role="assistant", text="Обсудим этот вариант.")],
        gateway=gateway,  # type: ignore[arg-type]
        demo_mode=False,
        poi_places=[poi],
    )

    assert '"poi_suggestions"' in gateway.prompt
    assert "Айя-София" in gateway.prompt
    assert "OpenStreetMap / Overpass" in gateway.prompt
    assert "Licensed Istanbul Guide" in gateway.prompt
    assert "пример подтверждённого описания" in gateway.prompt


def test_description_excerpt_stays_within_prompt_budget() -> None:
    text = "Подтверждённое описание. " * 80

    excerpt = _description_excerpt(text, max_chars=180)

    assert len(excerpt) <= 181
    assert excerpt.endswith("…")


async def test_destination_fallback_names_retrieved_pois_without_claiming_live_facts() -> None:
    request = trip_request()
    recommendation = rank_demo_candidates(request)[0]
    poi = PlaceSearchResult(
        place_id="00000000-0000-0000-0000-000000000002",
        name="Галатская башня",
        destination="istanbul",
        latitude=41.0256,
        longitude=28.9741,
        category="viewpoint",
        source=PlaceSource(
            name="OpenStreetMap / Overpass",
            url="https://www.openstreetmap.org/",
            attribution="© OpenStreetMap contributors",
        ),
        scores={"final": 0.8},
        reasons=["Совпало с тематикой запроса"],
        ranking_version="istanbul-hybrid-v1",
    )

    reply, warnings = await answer_destination_question(
        query="Где посмотреть закат?",
        trip_request=request,
        recommendation=recommendation,
        history=[],
        gateway=DisabledModelGateway("not configured"),
        demo_mode=True,
        poi_places=[poi],
    )

    assert "Галатская башня" in reply.answer
    assert "нужно проверить" in reply.answer
    assert warnings and "Локальный режим" in warnings[0]
