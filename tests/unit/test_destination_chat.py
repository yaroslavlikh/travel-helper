from typing import Any

from pydantic import BaseModel

from app.domain.models import (
    DestinationChatModelReply,
    DestinationThreadMessage,
    TravelRequest,
)
from app.services.destination_chat import answer_destination_question
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
    assert warnings and "AI-ответ" in warnings[0]
