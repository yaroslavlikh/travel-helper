from langgraph.checkpoint.memory import InMemorySaver

from app.observability.port import NoopObservability
from app.services.workflow import build_planner_graph


def test_graph_reaches_search_handoff_for_complete_request() -> None:
    graph = build_planner_graph(checkpointer=InMemorySaver(), observability=NoopObservability())

    result = graph.invoke(
        {
            "request_id": "request-1",
            "session_id": "session-1",
            "raw_query": (
                "Из Москвы в августе на море на 7–10 дней, 150 тысяч на одного, за границу"
            ),
        },
        {"configurable": {"thread_id": "session-1"}},
    )

    assert result["status"] == "ready_for_search"
    assert result["parsed_request"]["origin_city"] == "Москва"
    assert result["assumptions"]
