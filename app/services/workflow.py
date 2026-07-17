"""Checkpointed clarification workflow with deterministic control flow."""

from __future__ import annotations

from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from app.domain.models import Ambiguity, PlannerState, TravelRequest
from app.observability.port import ObservabilityPort
from app.services.ambiguity import (
    clarification_questions,
    detect_ambiguities,
    explicit_assumptions,
    next_best_question,
    planning_confidence,
)
from app.services.extraction import (
    extract_travel_request,
    extract_travel_request_with_model,
    merge_travel_request_answers,
    revise_travel_request_deterministically,
)
from app.services.model_gateway import ModelGateway, ModelGatewayError

type PlannerGraph = CompiledStateGraph[PlannerState, None, PlannerState, PlannerState]


def initialize_request(state: PlannerState) -> PlannerState:
    """Set workflow defaults without I/O or non-idempotent side effects."""

    return {**state, "status": "received", "warnings": state.get("warnings", [])}


async def extract_request(
    state: PlannerState, *, model_gateway: ModelGateway, demo_mode: bool
) -> PlannerState:
    """Build a validated request through AI, with an explicit demo-only fallback."""

    base_payload = state.get("previous_request") or state.get("parsed_request")
    base_request = TravelRequest.model_validate(base_payload) if base_payload else None
    try:
        parsed = await extract_travel_request_with_model(
            state["raw_query"],
            state.get("answers"),
            model_gateway,
            base_request=base_request,
        )
        return {"parsed_request": parsed.model_dump(mode="json")}
    except ModelGatewayError as error:
        if not demo_mode:
            raise
        if base_request is not None:
            revised = revise_travel_request_deterministically(base_request, state["raw_query"])
            parsed = merge_travel_request_answers(revised, state.get("answers"))
        else:
            parsed = extract_travel_request(state["raw_query"], state.get("answers"))
        fallback_warning = (
            "AI-разбор временно недоступен: использован ограниченный demo parser "
            f"({type(error).__name__}: {error})."
        )
        warnings = list(state.get("warnings", []))
        if fallback_warning not in warnings:
            warnings.append(fallback_warning)
        return {
            "parsed_request": parsed.model_dump(mode="json"),
            "warnings": warnings,
        }


def detect_request_ambiguities(state: PlannerState) -> PlannerState:
    """Classify unknowns and derive defaults without an LLM decision."""

    request = TravelRequest.model_validate(state["parsed_request"])
    ambiguities = detect_ambiguities(request)
    questions = clarification_questions(ambiguities)
    assumptions = explicit_assumptions(ambiguities)
    confidence = planning_confidence(ambiguities)
    advisory_question = next_best_question(ambiguities)
    question_history = list(state.get("question_history", []))
    if questions and not any(
        item.get("request_id") == state.get("request_id") for item in question_history
    ):
        question_history.append(
            {
                "request_id": state.get("request_id"),
                "questions": [item.model_dump(mode="json") for item in questions],
            }
        )
    return {
        "ambiguities": [item.model_dump(mode="json") for item in ambiguities],
        "questions": [item.model_dump(mode="json") for item in questions],
        "assumptions": assumptions,
        "planning_confidence": confidence.model_dump(mode="json"),
        "next_best_question": (
            advisory_question.model_dump(mode="json") if advisory_question else None
        ),
        "question_history": question_history[-50:],
    }


def route_after_ambiguities(
    state: PlannerState,
) -> Literal["ask_for_clarification", "ready_for_search"]:
    """Only P0 ambiguities stop the pipeline."""

    has_p0 = any(
        Ambiguity.model_validate(item).priority == "P0" for item in state.get("ambiguities", [])
    )
    return "ask_for_clarification" if has_p0 else "ready_for_search"


def ask_for_clarification(state: PlannerState) -> PlannerState:
    """Pause workflow with serializable questions and resume with an answer patch."""

    answer_patch: Any = interrupt({"questions": state.get("questions", [])})
    if not isinstance(answer_patch, dict):
        return {
            "answers": {},
            "warnings": [*state.get("warnings", []), "Ответы должны быть объектом field → value."],
        }
    return {"answers": answer_patch, "status": "received"}


def mark_ready_for_search(_: PlannerState) -> PlannerState:
    """End this slice at a deterministic hand-off to candidate generation."""

    return {"status": "ready_for_search"}


def build_planner_graph(
    *,
    checkpointer: BaseCheckpointSaver[str],
    observability: ObservabilityPort,
    model_gateway: ModelGateway,
    demo_mode: bool,
) -> PlannerGraph:
    """Compile a single-agent, resume-safe planner workflow."""

    def traced_initialize(state: PlannerState) -> PlannerState:
        with observability.span(
            "workflow.initialize_request", request_id=state.get("request_id")
        ) as observation:
            result = initialize_request(state)
            observation.update(output={"status": result.get("status")})
            return result

    async def traced_extraction(state: PlannerState) -> PlannerState:
        with observability.span(
            "request_extraction",
            request_id=state.get("request_id"),
            provider=model_gateway.provider_name,
            model=model_gateway.model_name,
        ) as observation:
            result = await extract_request(
                state,
                model_gateway=model_gateway,
                demo_mode=demo_mode,
            )
            parsed_request = result.get("parsed_request", {})
            observation.update(
                output={
                    "known_fields": sorted(
                        key
                        for key, value in parsed_request.items()
                        if key != "raw_query" and value not in (None, False, [])
                    )
                },
                metadata={"outcome": "success"},
            )
            return result

    def traced_ambiguity_detection(state: PlannerState) -> PlannerState:
        with observability.span(
            "ambiguity_detection", request_id=state.get("request_id")
        ) as observation:
            result = detect_request_ambiguities(state)
            observation.update(
                output={
                    "question_fields": [
                        question["field"] for question in result.get("questions", [])
                    ],
                    "question_count": len(result.get("questions", [])),
                    "planning_confidence": result.get("planning_confidence", {}).get("level"),
                    "next_best_question": (result.get("next_best_question") or {}).get("field"),
                }
            )
            return result

    def traced_clarification(state: PlannerState) -> PlannerState:
        questions = state.get("questions", [])
        with observability.span(
            "clarification_requested",
            request_id=state.get("request_id"),
            pipeline_stage="clarification",
            question_count=len(questions),
        ) as observation:
            observation.update(
                output={
                    "status": "waiting_for_user",
                    "question_fields": [question["field"] for question in questions],
                }
            )
        return ask_for_clarification(state)

    def ready_node(state: PlannerState) -> PlannerState:
        with observability.span(
            "ready_for_candidate_generation", request_id=state.get("request_id")
        ) as observation:
            result = mark_ready_for_search(state)
            observation.update(output={"status": result.get("status")})
            return result

    builder = StateGraph(PlannerState)
    builder.add_node("initialize_request", traced_initialize)
    builder.add_node("extract_request", traced_extraction)
    builder.add_node("detect_ambiguities", traced_ambiguity_detection)
    builder.add_node("ask_for_clarification", traced_clarification)
    builder.add_node("ready_for_search", ready_node)
    builder.add_edge(START, "initialize_request")
    builder.add_edge("initialize_request", "extract_request")
    builder.add_edge("extract_request", "detect_ambiguities")
    builder.add_conditional_edges("detect_ambiguities", route_after_ambiguities)
    builder.add_edge("ask_for_clarification", "extract_request")
    builder.add_edge("ready_for_search", END)
    return builder.compile(checkpointer=checkpointer)
