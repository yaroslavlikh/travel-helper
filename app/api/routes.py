"""Recommendation endpoint backed by the checkpointed LangGraph workflow."""

from __future__ import annotations

from typing import Any, Literal, cast
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request, Response, status
from langchain_core.runnables import RunnableConfig
from langgraph.types import Command

from app.api.schemas import (
    CompletedRecommendationResponse,
    DestinationChatInput,
    DestinationChatResponse,
    FeedbackInput,
    NeedsClarificationResponse,
    PartialRecommendationResponse,
    RecommendationResponse,
    RecommendInput,
    TravelLinkOpenedInput,
)
from app.core.resources import AppResources
from app.domain.models import (
    Ambiguity,
    DestinationThreadMessage,
    PlannerState,
    PlanningConfidence,
    ScoredDestination,
    TravelRequest,
    TravelRequestPatch,
)
from app.places.context import destination_context
from app.places.models import PlaceEventInput, PlaceSearchQuery, PlaceSearchResponse
from app.places.repository import PlacesUnavailableError
from app.services.aviasales import add_aviasales_links
from app.services.cached_flight_pricing import (
    apply_cached_flight_logistics,
    discover_cached_flights,
    preferred_cached_signal,
)
from app.services.destination_chat import answer_destination_question
from app.services.destination_pois import search_destination_pois
from app.services.extraction import extract_answers_for_questions
from app.services.fixtures import load_demo_candidates
from app.services.pricing_presentation import (
    cached_flight_card,
    cached_flight_unavailable_card,
)
from app.services.scoring import STRICT_BUDGET_FALLBACK, rank_candidates

router = APIRouter(tags=["recommendations"])


async def _require_planning_session_access(
    *, resources: AppResources, request: Request, session_id: str, csrf: bool
) -> None:
    """Keep account-owned thread IDs private without restricting guest threads."""

    account_session = await resources.auth_service.current_session(request)
    if account_session is None:
        if await resources.account_store.is_account_chat(session_id):
            raise HTTPException(status_code=404, detail="Unknown planning session")
        return
    await resources.auth_service.require_session(request, csrf=csrf)
    if not await resources.account_store.owns_chat(
        owner_id=account_session.account.id, chat_id=session_id
    ):
        raise HTTPException(status_code=404, detail="Unknown planning session")


@router.post("/places/search", response_model=PlaceSearchResponse, tags=["places"])
async def search_places(payload: PlaceSearchQuery, request: Request) -> PlaceSearchResponse:
    """Search published places from the canonical data store, never from demo fixtures."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    try:
        return await resources.places_repository.search(payload)
    except PlacesUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error


@router.post("/events/place", status_code=status.HTTP_204_NO_CONTENT, tags=["places"])
async def record_place_event(payload: PlaceEventInput, request: Request) -> Response:
    """Persist privacy-bounded place interaction telemetry for ranking evaluation."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    try:
        await resources.places_repository.record_event(payload)
    except PlacesUnavailableError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)
        ) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _state_to_request(state: PlannerState) -> TravelRequest:
    return TravelRequest.model_validate(state["parsed_request"])


def _state_to_questions(state: PlannerState) -> list[Ambiguity]:
    return [Ambiguity.model_validate(question) for question in state.get("questions", [])]


def _state_to_planning_confidence(state: PlannerState) -> PlanningConfidence:
    return PlanningConfidence.model_validate(state["planning_confidence"])


def _state_to_next_best_question(state: PlannerState) -> Ambiguity | None:
    payload = state.get("next_best_question")
    return Ambiguity.model_validate(payload) if payload else None


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
    next_question: Ambiguity | None = None,
) -> str:
    if status_value == "needs_clarification":
        if next_question is None:
            suffix = "вопрос" if question_count == 1 else "вопроса"
            return f"Я сохранил условия поездки. Осталось уточнить {question_count} {suffix}."
        return (
            f"Чтобы подобрать маршруты, подскажите: {next_question.question}\n\n"
            "Можно ответить как удобно, одной фразой."
        )
    if turn_kind == "refinement":
        message = (
            "Учёл уточнение и обновил ленту: сейчас в ней "
            f"{_recommendation_count_label(recommendation_count)}."
        )
    elif turn_kind == "clarification":
        message = (
            f"Спасибо, сохранил ответ и собрал {_recommendation_count_label(recommendation_count)}."
        )
    else:
        message = (
            f"Я разобрал запрос и собрал {_recommendation_count_label(recommendation_count)} "
            "для сравнения."
        )
    if next_question is None:
        return message
    return f"{message}\n\nХотите сузить выбор — подскажите: {next_question.question}"


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
    if existing_state is not None and graph_is_interrupted:
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
    turn_index: int,
) -> dict[str, Any]:
    if payload.answers is not None and graph_is_interrupted:
        if existing_state is None:
            raise HTTPException(status_code=404, detail="Unknown planning session")
        query_history = [*existing_state.get("query_history", []), payload.query.strip()][-20:]
        result = await resources.planner_graph.ainvoke(
            Command(
                resume=payload.answers,
                update={"query_history": query_history, "turn_count": turn_index},
            ),
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
                update={
                    "query_history": query_history,
                    "warnings": warnings,
                    "turn_count": turn_index,
                },
            ),
            config,
        )
        return cast(dict[str, Any], result)

    if turn_kind == "refinement" and existing_state is not None and previous_request is not None:
        refinement_state: PlannerState = {
            "request_id": str(uuid4()),
            "session_id": session_id,
            "raw_query": payload.query.strip(),
            "answers": payload.answers or {},
            "previous_request": previous_request.model_dump(mode="json"),
            "query_history": [
                *existing_state.get("query_history", []),
                payload.query.strip(),
            ][-20:],
            "question_history": existing_state.get("question_history", []),
            "destination_threads": existing_state.get("destination_threads", {}),
            "turn_count": turn_index,
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
        "destination_threads": {},
        "turn_count": turn_index,
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
            planning_confidence=_state_to_planning_confidence(typed_state),
            warnings=typed_state.get("warnings", []),
            turn_kind=turn_kind,
            assistant_message=_turn_message(
                status_value="needs_clarification",
                turn_kind=turn_kind,
                question_count=len(questions),
                next_question=questions[0] if questions else None,
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
            # Cached signals are limited to a deterministic candidate pool. They refine
            # date/logistics evidence only and never become a trip total or strict budget pass.
            initial_candidates = load_demo_candidates()
            discovery_pool = rank_candidates(parsed_request, initial_candidates, limit=12)
            cached_flights = await discover_cached_flights(
                request=parsed_request,
                candidates=[item.candidate for item in discovery_pool],
                provider=resources.pricing_providers.cached_flight,
            )
            recommendations = add_aviasales_links(
                rank_candidates(
                    parsed_request,
                    apply_cached_flight_logistics(initial_candidates, cached_flights),
                ),
                parsed_request,
                marker=resources.settings.aviasales_marker,
            )
            recommendations = [
                item.model_copy(
                    update={
                        "pricing": (
                            cached_flight_card(
                                cached_flights.get(item.candidate.destination_id, ())
                            )
                            if preferred_cached_signal(
                                cached_flights.get(item.candidate.destination_id, ())
                            )
                            else cached_flight_unavailable_card(parsed_request)
                        )
                    }
                )
                for item in recommendations
            ]
            await resources.planner_graph.aupdate_state(
                config,
                {
                    "recommendations": [item.model_dump(mode="json") for item in recommendations],
                    "cached_flight_signals": {
                        destination_id: [signal.model_dump(mode="json") for signal in signals]
                        for destination_id, signals in cached_flights.items()
                    },
                },
            )
            unavailable_entry_count = sum(
                "ENTRY_DATA_UNAVAILABLE"
                in (
                    item.candidate.entry_assessment.warnings
                    if item.candidate.entry_assessment
                    else []
                )
                for item in recommendations
            )
            scoring_observation.update(
                output={
                    "recommendation_count": len(recommendations),
                    "entry_data_unavailable_count": unavailable_entry_count,
                    "cached_flight_signal_count": sum(
                        len(items) for items in cached_flights.values()
                    ),
                },
                metadata={
                    "outcome": "success",
                    "entry_data_status": "unavailable" if unavailable_entry_count else "available",
                },
            )
        return CompletedRecommendationResponse(
            status="completed",
            request_id=typed_state["request_id"],
            session_id=session_id,
            parsed_request=parsed_request,
            assumptions=typed_state.get("assumptions", []),
            planning_confidence=_state_to_planning_confidence(typed_state),
            next_best_question=_state_to_next_best_question(typed_state),
            recommendations=recommendations,
            warnings=[
                *typed_state.get("warnings", []),
                *(
                    [STRICT_BUDGET_FALLBACK]
                    if any(STRICT_BUDGET_FALLBACK in item.assumptions for item in recommendations)
                    else []
                ),
                "Результаты используют локальный demo fixture, а не live search sources.",
            ],
            turn_kind=turn_kind,
            assistant_message=_turn_message(
                status_value="completed",
                turn_kind=turn_kind,
                recommendation_count=len(recommendations),
                next_question=_state_to_next_best_question(typed_state),
            ),
            changed_fields=_changed_fields(previous_request, parsed_request),
        )
    return PartialRecommendationResponse(
        status="partial",
        request_id=typed_state["request_id"],
        session_id=session_id,
        parsed_request=parsed_request,
        assumptions=typed_state.get("assumptions", []),
        planning_confidence=_state_to_planning_confidence(typed_state),
        next_best_question=_state_to_next_best_question(typed_state),
        warnings=[
            *typed_state.get("warnings", []),
            "Поиск и ранжирование направлений будут добавлены следующим этапом.",
        ],
        turn_kind=turn_kind,
        assistant_message=_turn_message(
            status_value="partial",
            turn_kind=turn_kind,
            next_question=_state_to_next_best_question(typed_state),
        ),
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
        "planning_confidence": response.planning_confidence.level,
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


def _recommendation_trace_name(
    turn_index: int, turn_kind: Literal["initial", "clarification", "refinement"]
) -> str:
    labels = {
        "initial": "initial request",
        "clarification": "clarification",
        "refinement": "refinement",
    }
    return f"Turn {turn_index:02d} · {labels[turn_kind]}"


def _destination_trace_input(
    payload: DestinationChatInput, *, capture_content: bool
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "query_length": len(payload.query),
        "destination_id": payload.destination_id,
    }
    if capture_content:
        result["query"] = payload.query
    return result


def _find_current_recommendation(
    *, destination_id: str, recommendation_snapshot_id: str | None, state: PlannerState
) -> ScoredDestination | None:
    """Use the card actually shown to the traveller, never re-rank it during a subchat."""

    for raw_item in state.get("recommendations", []):
        try:
            # Local checkpoints from the removed modelled-pricing slice retain these fields.
            # They are presentation-only, so safely ignore them while preserving the card snapshot.
            item = ScoredDestination.model_validate(
                {
                    key: value
                    for key, value in raw_item.items()
                    if key not in {"trip_cost_estimate", "price_card_view"}
                }
                if isinstance(raw_item, dict)
                else raw_item
            )
        except (TypeError, ValueError):
            continue
        if item.candidate.destination_id != destination_id:
            continue
        if (
            recommendation_snapshot_id
            and item.recommendation_snapshot_id != recommendation_snapshot_id
        ):
            continue
        return item
    return None


@router.post("/feedback", status_code=status.HTTP_204_NO_CONTENT)
async def submit_feedback(payload: FeedbackInput, request: Request) -> Response:
    """Record minimal anonymous product feedback without user accounts."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    await resources.feedback_store.record(
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
    await resources.product_event_store.record_travel_link_opened(
        session_id=payload.session_id,
        request_id=payload.request_id,
        destination_id=payload.destination_id,
        rank=payload.rank,
        provider=payload.provider,
        link_kind=payload.link_kind,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/destination-chat", response_model=DestinationChatResponse)
async def destination_chat(
    payload: DestinationChatInput, request: Request
) -> DestinationChatResponse:
    """Continue a bounded card-specific conversation inside the parent trip session."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")
    await _require_planning_session_access(
        resources=resources, request=request, session_id=payload.session_id, csrf=True
    )
    config: RunnableConfig = {"configurable": {"thread_id": payload.session_id}}
    snapshot = await resources.planner_graph.aget_state(config)
    if not snapshot.values:
        raise HTTPException(status_code=404, detail="Unknown planning session")
    state = cast(PlannerState, snapshot.values)
    if snapshot.next or not state.get("parsed_request"):
        raise HTTPException(
            status_code=409,
            detail="Complete the main trip clarification before discussing a destination",
        )
    trip_request = _state_to_request(state)
    recommendation = _find_current_recommendation(
        destination_id=payload.destination_id,
        recommendation_snapshot_id=payload.recommendation_snapshot_id,
        state=state,
    )
    if recommendation is None:
        raise HTTPException(status_code=404, detail="Destination is not in the current shortlist")

    destination = recommendation.candidate
    subthread_id = f"destination:{destination.destination_id}"
    raw_threads = state.get("destination_threads", {})
    threads = dict(raw_threads) if isinstance(raw_threads, dict) else {}
    raw_thread = threads.get(destination.destination_id, {})
    raw_history = raw_thread.get("messages", []) if isinstance(raw_thread, dict) else []
    history: list[DestinationThreadMessage] = []
    for item in raw_history[-20:]:
        try:
            history.append(DestinationThreadMessage.model_validate(item))
        except (TypeError, ValueError):
            continue
    turn_index = max(state.get("turn_count", 0), len(state.get("query_history", []))) + 1
    request_id = str(uuid4())
    trace_name = f"Turn {turn_index:02d} · destination question · {destination.city_or_region}"
    with resources.observability.trace(
        "destination_conversation",
        session_id=payload.session_id,
        trace_name=trace_name,
        input=_destination_trace_input(
            payload,
            capture_content=resources.settings.langfuse_capture_content,
        ),
        metadata={
            "turn_id": request_id,
            "turn_kind": "destination_question",
            "turn_index": turn_index,
            "subthread_id": subthread_id,
            "destination_id": destination.destination_id,
            "demo_mode": resources.settings.demo_mode,
        },
        tags=["travel-chat", "destination-question"],
    ) as trace:
        poi_search = await search_destination_pois(
            destination_id=destination.destination_id,
            query=payload.query.strip(),
            repository=resources.places_repository,
        )
        reply, warnings = await answer_destination_question(
            query=payload.query.strip(),
            trip_request=trip_request,
            recommendation=recommendation,
            history=history,
            gateway=resources.model_gateway,
            demo_mode=resources.settings.demo_mode,
            poi_places=poi_search.places,
            destination_context=destination_context(destination.destination_id),
        )
        updated_history = [
            *history,
            DestinationThreadMessage(role="user", text=payload.query.strip()),
            DestinationThreadMessage(role="assistant", text=reply.answer),
        ][-20:]
        threads[destination.destination_id] = {
            "destination_id": destination.destination_id,
            "messages": [item.model_dump(mode="json") for item in updated_history],
        }
        await resources.planner_graph.aupdate_state(
            config,
            {"destination_threads": threads, "turn_count": turn_index},
        )
        response = DestinationChatResponse(
            status="completed",
            request_id=request_id,
            session_id=payload.session_id,
            subthread_id=subthread_id,
            destination_id=destination.destination_id,
            destination_name=destination.city_or_region,
            assistant_message=reply.answer,
            quick_replies=reply.quick_replies,
            places=poi_search.places,
            place_retrieval_id=str(poi_search.retrieval_id) if poi_search.retrieval_id else None,
            place_ranking_version=poi_search.ranking_version,
            proposed_trip_change=reply.proposed_trip_change,
            message_count=len(updated_history),
            turn_index=turn_index,
            warnings=[*poi_search.user_warnings, *warnings],
        )
        trace.update(
            output={
                "status": response.status,
                "request_id": request_id,
                "destination_id": destination.destination_id,
                "message_count": response.message_count,
                "proposed_trip_change": bool(response.proposed_trip_change),
                "poi_count": len(response.places),
                "poi_description_count": sum(bool(place.description) for place in response.places),
                "poi_retrieval_id": response.place_retrieval_id,
            },
            metadata={"outcome": "completed"},
        )
        return response


@router.post("/recommend", response_model=RecommendationResponse)
async def recommend(payload: RecommendInput, request: Request) -> RecommendationResponse:
    """Start, resume, or refine one anonymous planning thread."""

    resources = request.app.state.resources
    if not isinstance(resources, AppResources):
        raise RuntimeError("Application resources are unavailable")

    account_session = await resources.auth_service.current_session(request)
    if account_session is not None:
        if payload.session_id is None:
            await resources.auth_service.require_session(request, csrf=True)
            account_chat = await resources.account_store.create_chat(
                owner_id=account_session.account.id,
                title="Новая поездка",
                payload={},
            )
            session_id = account_chat.id
        else:
            await _require_planning_session_access(
                resources=resources, request=request, session_id=payload.session_id, csrf=True
            )
            session_id = payload.session_id
    else:
        session_id = payload.session_id or str(uuid4())
        if payload.session_id is not None:
            await _require_planning_session_access(
                resources=resources, request=request, session_id=session_id, csrf=False
            )
    config: RunnableConfig = {"configurable": {"thread_id": session_id}}
    snapshot = await resources.planner_graph.aget_state(config)
    existing_state = cast(PlannerState, snapshot.values) if snapshot.values else None
    if existing_state is None and account_session is not None:
        restored_chat = await resources.account_store.get_chat(
            owner_id=account_session.account.id, chat_id=session_id
        )
        stored_payload = restored_chat.payload if restored_chat else {}
        stored_snapshot = stored_payload.get("snapshot")
        parsed_payload = (
            stored_snapshot.get("parsed_request") if isinstance(stored_snapshot, dict) else None
        )
        if isinstance(stored_snapshot, dict) and isinstance(parsed_payload, dict):
            try:
                restored_request = TravelRequest.model_validate(parsed_payload)
            except ValueError:
                restored_request = None
            if restored_request is not None:
                raw_messages = stored_payload.get("messages", [])
                query_history = [
                    str(message.get("text", ""))
                    for message in raw_messages
                    if isinstance(message, dict)
                    and message.get("role") == "user"
                    and message.get("text")
                ][-20:]
                raw_threads = stored_payload.get("destinationThreads", {})
                restored_state: PlannerState = {
                    "request_id": str(stored_snapshot.get("request_id", uuid4())),
                    "session_id": session_id,
                    "parsed_request": restored_request.model_dump(mode="json"),
                    "query_history": query_history,
                    "question_history": [],
                    "destination_threads": raw_threads if isinstance(raw_threads, dict) else {},
                    "turn_count": len(query_history),
                    "warnings": [],
                    "status": "ready_for_search",
                }
                existing_state = restored_state
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
    turn_index = (
        max(
            (existing_state or {}).get("turn_count", 0),
            len((existing_state or {}).get("query_history", [])),
        )
        + 1
    )
    turn_id = str(uuid4())

    with resources.observability.trace(
        "recommendation_pipeline",
        session_id=session_id,
        trace_name=_recommendation_trace_name(turn_index, turn_kind),
        input=_trace_input(
            payload,
            capture_content=resources.settings.langfuse_capture_content,
        ),
        metadata={
            "turn_id": turn_id,
            "turn_kind": turn_kind,
            "turn_index": turn_index,
            "demo_mode": resources.settings.demo_mode,
            "has_answers": payload.answers is not None,
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
            turn_index=turn_index,
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
