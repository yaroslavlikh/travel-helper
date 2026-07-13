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
        return f"Учёл уточнение и обновил ленту: сейчас в ней {recommendation_count} вариантов."
    if turn_kind == "clarification":
        return f"Спасибо, сохранил ответ и собрал {recommendation_count} вариантов."
    return f"Я разобрал запрос и собрал {recommendation_count} вариантов для сравнения."


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
    turn_kind: Literal["initial", "clarification", "refinement"] = "initial"

    with resources.observability.span(
        "recommendation_pipeline",
        session_id=session_id,
        pipeline_stage="root_request",
        has_clarification_answers=payload.answers is not None,
    ):
        if payload.answers is not None:
            if existing_state is None or not snapshot.next:
                raise HTTPException(status_code=404, detail="Unknown planning session")
            turn_kind = "clarification"
            query_history = [
                *existing_state.get("query_history", []),
                payload.query.strip(),
            ][-20:]
            result = await resources.planner_graph.ainvoke(
                Command(resume=payload.answers, update={"query_history": query_history}),
                config,
            )
        elif existing_state is not None and snapshot.next:
            turn_kind = "clarification"
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
            query_history = [
                *existing_state.get("query_history", []),
                payload.query.strip(),
            ][-20:]
            result = await resources.planner_graph.ainvoke(
                Command(
                    resume=answer_patch,
                    update={"query_history": query_history, "warnings": warnings},
                ),
                config,
            )
        elif existing_state is not None and previous_request is not None:
            turn_kind = "refinement"
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
        else:
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
            result = await resources.planner_graph.ainvoke(
                initial_state,
                config,
            )

    state = cast(dict[str, Any], result)
    if "__interrupt__" in state:
        snapshot = await resources.planner_graph.aget_state(config)
        typed_state = cast(PlannerState, snapshot.values)
        return NeedsClarificationResponse(
            status="needs_clarification",
            request_id=typed_state["request_id"],
            session_id=session_id,
            parsed_request=_state_to_request(typed_state),
            questions=_state_to_questions(typed_state),
            assumptions=typed_state.get("assumptions", []),
            warnings=typed_state.get("warnings", []),
            turn_kind=turn_kind,
            assistant_message=_turn_message(
                status_value="needs_clarification",
                turn_kind=turn_kind,
                question_count=len(_state_to_questions(typed_state)),
            ),
            changed_fields=_changed_fields(previous_request, _state_to_request(typed_state)),
        )

    typed_state = cast(PlannerState, state)
    parsed_request = _state_to_request(typed_state)
    if resources.settings.demo_mode:
        with resources.observability.span(
            "deterministic_scoring",
            request_id=typed_state["request_id"],
            pipeline_stage="scoring",
        ):
            recommendations = rank_demo_candidates(parsed_request)
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
        assistant_message=_turn_message(
            status_value="partial",
            turn_kind=turn_kind,
        ),
        changed_fields=_changed_fields(previous_request, parsed_request),
    )
