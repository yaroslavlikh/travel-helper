import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from app.observability.port import NoopObservability
from app.services.model_gateway import DisabledModelGateway
from app.services.workflow import build_planner_graph


@pytest.mark.asyncio
async def test_graph_reaches_search_handoff_for_complete_request() -> None:
    graph = build_planner_graph(
        checkpointer=InMemorySaver(),
        observability=NoopObservability(),
        model_gateway=DisabledModelGateway("test fallback"),
        demo_mode=True,
    )

    result = await graph.ainvoke(
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
    assert "demo parser (ModelConfigurationError: test fallback)" in result["warnings"][0]


@pytest.mark.asyncio
async def test_graph_retains_answers_across_multiple_clarification_rounds() -> None:
    graph = build_planner_graph(
        checkpointer=InMemorySaver(),
        observability=NoopObservability(),
        model_gateway=DisabledModelGateway("test fallback"),
        demo_mode=True,
    )
    config = {"configurable": {"thread_id": "session-multiple-answers"}}

    first = await graph.ainvoke(
        {
            "request_id": "request-multiple-answers",
            "session_id": "session-multiple-answers",
            "raw_query": "Хочу на море",
        },
        config,
    )
    second = await graph.ainvoke(
        Command(resume={"origin_city": "Москва", "month": 8, "adults": 2}),
        config,
    )
    completed = await graph.ainvoke(
        Command(resume={"budget_total_rub": 180_000, "destination_scope": "international"}),
        config,
    )

    assert "__interrupt__" in first
    assert "__interrupt__" in second
    assert completed["status"] == "ready_for_search"
    assert completed["parsed_request"]["origin_city"] == "Москва"
    assert completed["parsed_request"]["month"] == 8
    assert completed["parsed_request"]["adults"] == 2
    assert completed["parsed_request"]["budget_total_rub"] == 180_000
    assert completed["parsed_request"]["destination_scope"] == "international"
