"""The first compiled LangGraph workflow and its deterministic bootstrap node."""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.domain.models import PlannerState
from app.observability.port import ObservabilityPort


def initialize_request(state: PlannerState) -> PlannerState:
    """Set the initial workflow state without I/O or non-idempotent side effects."""

    return {**state, "status": "ready", "warnings": state.get("warnings", [])}


def build_planner_graph(
    *, checkpointer: BaseCheckpointSaver[str], observability: ObservabilityPort
) -> CompiledStateGraph[PlannerState, None, PlannerState, PlannerState]:
    """Compile the stable workflow shell used by upcoming planner nodes."""

    def traced_initialize(state: PlannerState) -> PlannerState:
        with observability.span("workflow.initialize_request", request_id=state.get("request_id")):
            return initialize_request(state)

    builder = StateGraph(PlannerState)
    builder.add_node("initialize_request", traced_initialize)
    builder.add_edge(START, "initialize_request")
    builder.add_edge("initialize_request", END)
    return builder.compile(checkpointer=checkpointer)
