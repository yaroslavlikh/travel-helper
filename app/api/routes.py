"""Recommendation endpoint backed by the checkpointed LangGraph workflow."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.api.schemas import (
    CompletedRecommendationResponse,
    FeedbackInput,
    NeedsClarificationResponse,
    PartialRecommendationResponse,
    RecommendationResponse,
    RecommendInput,
    TravelLinkOpenedInput,
)
from app.core.resources import AppResources
from app.domain.models import Ambiguity, PlannerState, TravelRequest, TravelRequestPatch
from app.services.extraction import extract_answers_for_questions
from app.services.scoring import rank_demo_candidates

router = APIRouter(tags=["recommendations"])


def _state_to_request(state: PlannerState) -> TravelRequest:
    return TravelRequest.model_validate(state["parsed_request"])


def _state_to_questions(state: PlannerState) -> list[Ambiguity]:
    return [Ambiguity.model_validate(question) for question in state.get("questions", [])]


def _changed_fields(previous: TravelRequest | None, current: TravelRequest) -> list[str]:
    fields: list[str] = []
    for field in TravelRequestPatch.model_fields:
        current_value = getattr(current, field)
        if previous is None:
            if current_value not in (None, False, []):
                fields.append(field)
        elif getattr(previous, field) != current_value:
            fields.append(field)
    return fields


def _turn_message(
    *,
    status_value: str,
    turn_kind: Literal["initial", "clarification", "refinement"],
    question_count: int = 0,
    recommendation_count: int = 0,
) -> str:
    if status_value == "needs_clarification":
        suffix = "вопрос" if question_count == 1 else "вопроса"
        return f"Я сохранил условия поездки. Осталось уточнить {question_count} {suffix}."
    if turn_kind == "refinement":
        return (
            "Учёл уточнение и обновил ленту: сейчас в ней "
            f"{_recommendation_count_label(recommendation_count)}."
        )
    if turn_kind == "clarification":
        return (
            f"Спасибо, сохранил ответ и собрал {_recommendation_count_label(recommendation_count)}."
        )
    return (
        f"Я разобрал запрос и собрал {_recommendation_count_label(recommendation_count)} "
        "для сравнения."
    )


def _recommendation_count_label(count: int) -> str:
    last = count % 10
    last_two = count % 100
    if last == 1 and last_two != 11:
        return f"{count} вариант"
    if last in {2, 3, 4} and last_two not in {12, 13, 14}:
        return f"{count} варианта"
    return f"{count} вариантов"


def _classify_turn(
    payload: RecommendInput,
    *,
    existing_state: PlannerState | None,
    graph_is_interrupted: bool,
    previous_request: TravelRequest | None,
) -> Literal["initial", "clarification", "refinement"]:
    if payload.answers is not None or (existing_state is not None and graph_is_interrupted):
        return "clarification"
    if existing_state is not None and previous_request is not None:
        return "refinement"
    return "initial"


async def _invoke_planner_turn(
    *,
    payload: RecommendInput,
    resources: AppResources,
    config: RunnableConfig,
    session_id: str,
    existing_state: PlannerState | None,
    graph_is_interrupted: bool,
    previous_request: TravelRequest | None,
    turn_kind: Literal["initial", "clarification", "refinement"],
) -> dict[str, Any]:
    if payload.answers is not None:
        if existing_state is None or not graph_is_interrupted:
            raise HTTPException(status_code=404, detail="Unknown planning session")
        query_history = [*existing_state.get("query_history", []), payload.query.strip()][-20:]
        result = await resources.planner_graph.ainvoke(
            Command(resume=payload.answers, update={"query_history": query_history}),
            config,
        )
        return cast(dict[str, Any], result)

    if existing_state is not None and graph_is_interrupted:
        questions = _state_to_questions(existing_state)
        answer_patch = await extract_answers_for_questions(
            payload.query.strip(),
            questions,
            resources.model_gateway,
            demo_mode=resources.settings.demo_mode,
        )
        warnings = list(existing_state.get("warnings", []))
        if not answer_patch:
            warnings.append(
                "Не удалось связать ответ с текущими вопросами — уточните формулировку."
            )
        query_history = [*existing_state.get("query_history", []), payload.query.strip()][-20:]
        result = await resources.planner_graph.ainvoke(
            Command(
                resume=answer_patch,
                update={"query_history": query_history, "warnings": warnings},
            ),
            config,
        )
        return cast(dict[str, Any], result)

    if turn_kind == "refinement" and existing_state is not None and previous_request is not None:
        refinement_state: PlannerState = {
            "request_id": str(uuid4()),
            "session_id": session_id,
            "raw_query": payload.query.strip(),
            "answers": {},
            "previous_request": previous_request.model_dump(mode="json"),
            "query_history": [
                *existing_state.get("query_history", []),
                payload.query.strip(),
            ][-20:],
            "question_history": existing_state.get("question_history", []),
            "ambiguities": [],
            "questions": [],
            "assumptions": [],
            "warnings": [],
            "status": "received",
        }
        result = await resources.planner_graph.ainvoke(refinement_state, config)
        return cast(dict[str, Any], result)

    initial_state: PlannerState = {
        "request_id": str(uuid4()),
        "session_id": session_id,
        "raw_query": payload.query.strip(),
        "answers": {},
        "query_history": [payload.query.strip()],
        "question_history": [],
        "warnings": [],
        "status": "received",
    }
    result = await resources.planner_graph.ainvoke(initial_state, config)
    return cast(dict[str, Any], result)


async def _build_recommendation_response(
    *,
    result: dict[str, Any],
    resources: AppResources,
    config: RunnableConfig,
    session_id: str,
    previous_request: TravelRequest | None,
    turn_kind: Literal["initial", "clarification", "refinement"],
) -> RecommendationResponse:
    if "__interrupt__" in result:
        snapshot = await resources.planner_graph.aget_state(config)
        typed_state = cast(PlannerState, snapshot.values)
        questions = _state_to_questions(typed_state)
        return NeedsClarificationResponse(
            status="needs_clarification",
            request_id=typed_state["request_id"],
            session_id=session_id,
            parsed_request=_state_to_request(typed_state),
            questions=questions,
            assumptions=typed_state.get("assumptions", []),
            warnings=typed_state.get("warnings", []),
            turn_kind=turn_kind,
            assistant_message=_turn_message(
                status_value="needs_clarification",
                turn_kind=turn_kind,
                question_count=len(questions),
            ),
            changed_fields=_changed_fields(previous_request, _state_to_request(typed_state)),
        )

    typed_state = cast(PlannerState, result)
    parsed_request = _state_to_request(typed_state)
    if resources.settings.demo_mode:
        with resources.observability.span(
            "deterministic_scoring",
            request_id=typed_state["request_id"],
            pipeline_stage="scoring",
        ) as scoring_observation:
            recommendations = rank_demo_candidates(parsed_request)
            scoring_observation.update(
                output={"recommendation_count": len(recommendations)},
                metadata={"outcome": "success"},
            )
        return CompletedRecommendationResponse(
            status="completed",
            request_id=typed_state["request_id"],
            session_id=session_id,
            parsed_request=parsed_request,
            assumptions=typed_state.get("assumptions", []),
            recommendations=recommendations,
            warnings=[
                *typed_state.get("warnings", []),
                "Результаты используют локальный demo fixture, а не live search sources.",
            ],
            turn_kind=turn_kind,
            assistant_message=_turn_message(
                status_value="completed",
                turn_kind=turn_kind,
                recommendation_count=len(recommendations),
            ),
            changed_fields=_changed_fields(previous_request, parsed_request),
        )
    return PartialRecommendationResponse(
        status="partial",
        request_id=typed_state["request_id"],
        session_id=session_id,
        parsed_request=parsed_request,
        assumptions=typed_state.get("assumptions", []),
        warnings=[
            *typed_state.get("warnings", []),
            "Поиск и ранжирование направлений будут добавлены следующим этапом.",
        ],
        turn_kind=turn_kind,
        assistant_message=_turn_message(status_value="partial", turn_kind=turn_kind),
        changed_fields=_changed_fields(previous_request, parsed_request),
    )


def _trace_input(payload: RecommendInput, *, capture_content: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query_length": len(payload.query),
        "answer_fields": sorted((payload.answers or {}).keys()),
    }
    if capture_content:
        result["query"] = payload.query
        result["answers"] = payload.answers
    return result


def _trace_output(
    response: RecommendationResponse,
    *,
    capture_content: bool,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "status": response.status,
        "turn_kind": response.turn_kind,
        "request_id": response.request_id,
        "changed_fields": response.changed_fields,
    }
    if isinstance(response, NeedsClarificationResponse):
        result["question_count"] = len(response.questions)
        result["question_fields"] = [question.field for question in response.questions]
        if capture_content:
            result["questions"] = [question.question for question in response.questions]
    elif isinstance(response, CompletedRecommendationResponse):
        result["recommendation_count"] = len(response.recommendations)
        result["destination_ids"] = [
            recommendation.candidate.destination_id for recommendation in response.recommendations
        ]
    return result


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(payload: FeedbackInput, request: Request) -> Response:
    """Record minimal anonymous product feedback without user accounts."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    resources.feedback_store.record(
        session_id=payload.session_id,
        request_id=payload.request_id,
        destination_id=payload.destination_id,
        value=payload.value,
        comment=payload.comment,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/events/travel-link", status_code=status.HTTP_204_NO_CONTENT)
async def record_travel_link_opened(payload: TravelLinkOpenedInput, request: Request) -> Response:
    """Record a bounded anonymous provider click without delaying navigation."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    resources.product_event_store.record_travel_link_opened(
        session_id=payload.session_id,
        request_id=payload.request_id,
        destination_id=payload.destination_id,
        rank=payload.rank,
        provider=payload.provider,
        link_kind=payload.link_kind,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(payload: RecommendInput, request: Request) -> RecommendationResponse:
    """Start, resume, or refine one anonymous planning thread."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")

    session_id = payload.session_id or str(uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    snapshot = await resources.planner_graph.aget_state(config)
    existing_state = cast(PlannerState, snapshot.values) if snapshot.values else None
    previous_request = (
        _state_to_request(existing_state)
        if existing_state is not None and existing_state.get("parsed_request")
        else None
    )
    graph_is_interrupted = bool(snapshot.next)
    turn_kind = _classify_turn(
        payload,
        existing_state=existing_state,
        graph_is_interrupted=graph_is_interrupted,
        previous_request=previous_request,
    )
    turn_id = str(uuid4())

    with resources.observability.trace(
        "recommendation_pipeline",
        session_id=session_id,
        input=_trace_input(
            payload,
            capture_content=resources.settings.langfuse_capture_content,
        ),
        metadata={
            "turnid": turn_id,
            "turnkind": turn_kind,
            "demomode": resources.settings.demo_mode,
            "hasanswers": payload.answers is not None,
        },
        tags=["travel-chat", turn_kind],
    ) as trace:
        result = await _invoke_planner_turn(
            payload=payload,
            resources=resources,
            config=config,
            session_id=session_id,
            existing_state=existing_state,
            graph_is_interrupted=graph_is_interrupted,
            previous_request=previous_request,
            turn_kind=turn_kind,
        )
        response = await _build_recommendation_response(
            result=result,
            resources=resources,
            config=config,
            session_id=session_id,
            previous_request=previous_request,
            turn_kind=turn_kind,
        )
        trace.update(
            output=_trace_output(
                response,
                capture_content=resources.settings.langfuse_capture_content,
            ),
            metadata={"request_id": response.request_id, "outcome": response.status},
        )
        return response
