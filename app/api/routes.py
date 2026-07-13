"""Recommendation endpoint backed by the checkpointed LangGraph workflow."""

from __future__ import annotations

from typing import Any, cast
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
from app.domain.models import Ambiguity, PlannerState, TravelRequest
from app.services.scoring import rank_demo_candidates

router = APIRouter(tags=["recommendations"])


def _state_to_request(state: PlannerState) -> TravelRequest:
    return TravelRequest.model_validate(state["parsed_request"])


def _state_to_questions(state: PlannerState) -> list[Ambiguity]:
    return [Ambiguity.model_validate(question) for question in state.get("questions", [])]


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
    """Start or resume one anonymous planning thread without exposing checkpoints."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")

    session_id = payload.session_id or str(uuid4())
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    with resources.observability.span(
        "recommendation_pipeline",
        session_id=session_id,
        pipeline_stage="root_request",
        has_clarification_answers=payload.answers is not None,
    ):
        if payload.answers is not None:
            snapshot = resources.planner_graph.get_state(config)
            if not snapshot.values:
                raise HTTPException(status_code=404, detail="Unknown planning session")
            result = resources.planner_graph.invoke(Command(resume=payload.answers), config)
        else:
            initial_state: PlannerState = {
                "request_id": str(uuid4()),
                "session_id": session_id,
                "raw_query": payload.query.strip(),
                "status": "received",
            }
            result = resources.planner_graph.invoke(
                initial_state,
                config,
            )

    state = cast(dict[str, Any], result)
    if "__interrupt__" in state:
        snapshot = resources.planner_graph.get_state(config)
        typed_state = cast(PlannerState, snapshot.values)
        return NeedsClarificationResponse(
            status="needs_clarification",
            request_id=typed_state["request_id"],
            session_id=session_id,
            parsed_request=_state_to_request(typed_state),
            questions=_state_to_questions(typed_state),
            assumptions=typed_state.get("assumptions", []),
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
            warnings=["Результаты используют локальный demo fixture, а не live search sources."],
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
    )
