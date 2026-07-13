from langgraph.checkpoint.memory import InMemorySaver

from app.observability.port import NoopObservability
from app.services.workflow import build_planner_graph


def test_bootstrap_graph_initializes_request() -> None:
    graph = build_planner_graph(checkpointer=InMemorySaver(), observability=NoopObservability())

    result = graph.invoke(
        {"request_id": "request-1", "session_id": "session-1"},
        {"configurable": {"thread_id": "session-1"}},
    )

    assert result["status"] == "ready"
    assert result["warnings"] == []
