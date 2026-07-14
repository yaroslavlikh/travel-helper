from contextlib import contextmanager
from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


class RecordedObservation:
    def __init__(self, record: dict[str, Any]) -> None:
        self.record = record

    def update(self, **kwargs: Any) -> None:
        self.record.setdefault("updates", []).append(kwargs)


class RecordingObservability:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    @property
    def backend_name(self) -> str:
        return "recorder"

    @contextmanager
    def trace(self, name: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        record = {"type": "trace", "name": name, **kwargs}
        self.records.append(record)
        yield RecordedObservation(record)

    @contextmanager
    def span(self, name: str, **metadata: Any):  # type: ignore[no-untyped-def]
        record = {"type": "span", "name": name, "metadata": metadata}
        self.records.append(record)
        yield RecordedObservation(record)

    @contextmanager
    def generation(self, name: str, **kwargs: Any):  # type: ignore[no-untyped-def]
        record = {"type": "generation", "name": name, **kwargs}
        self.records.append(record)
        yield RecordedObservation(record)

    def flush(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


@pytest.mark.asyncio
async def test_health_exposes_safe_demo_status() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "environment": "test",
        "mode": "demo",
        "version": "0.1.0",
        "providers": [
            {"name": "llm", "status": "disabled"},
            {"name": "noop", "status": "deferred"},
        ],
    }


@pytest.mark.asyncio
async def test_recommendation_clarifies_then_resumes_same_session() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Из Москвы на море в августе на 7–10 дней, 150 тысяч на одного, без жары"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            clarification = await client.post("/recommend", json={"query": query})
            initial_body = clarification.json()
            resumed = await client.post(
                "/recommend",
                json={
                    "query": "Давайте только за границу",
                    "session_id": initial_body["session_id"],
                },
            )

    assert clarification.status_code == 200
    assert initial_body["status"] == "needs_clarification"
    assert [question["field"] for question in initial_body["questions"]] == ["destination_scope"]
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["turn_kind"] == "clarification"
    assert resumed.json()["parsed_request"]["destination_scope"] == "international"
    assert len(resumed.json()["recommendations"]) >= 3


@pytest.mark.asyncio
async def test_clarification_is_recorded_as_session_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingObservability()
    monkeypatch.setattr("app.main.create_observability", lambda _: recorder)
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/recommend", json={"query": "Хочу на море"})

    body = response.json()
    root = next(record for record in recorder.records if record["type"] == "trace")
    clarification = next(
        record for record in recorder.records if record["name"] == "clarification_requested"
    )

    assert body["status"] == "needs_clarification"
    assert root["session_id"] == body["session_id"]
    assert root["name"] == "recommendation_pipeline"
    assert root["trace_name"] == "Turn 01 · initial request"
    assert root["updates"][-1]["output"]["status"] == "needs_clarification"
    assert root["updates"][-1]["output"]["question_count"] == 3
    assert clarification["updates"][-1]["output"] == {
        "status": "waiting_for_user",
        "question_fields": ["origin_city", "month", "adults"],
    }


@pytest.mark.asyncio
async def test_follow_up_refines_existing_request_without_forgetting_it() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Из Москвы на море в августе на неделю, 180 тысяч на одного, за границу"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.post("/recommend", json={"query": query})
            initial_body = initial.json()
            refined = await client.post(
                "/recommend",
                json={
                    "query": "Перелёт максимум четыре часа",
                    "session_id": initial_body["session_id"],
                },
            )

    refined_body = refined.json()
    assert initial_body["status"] == "completed"
    assert refined_body["status"] == "completed"
    assert refined_body["turn_kind"] == "refinement"
    assert refined_body["parsed_request"]["budget_total_rub"] == 180_000
    assert refined_body["parsed_request"]["origin_city"] == "Москва"
    assert refined_body["parsed_request"]["max_flight_duration_hours"] == 4
    assert refined_body["changed_fields"] == ["max_flight_duration_hours"]


@pytest.mark.asyncio
async def test_destination_subthread_keeps_memory_and_session_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recorder = RecordingObservability()
    monkeypatch.setattr("app.main.create_observability", lambda _: recorder)
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Из Москвы на море в августе на неделю, 180 тысяч на одного, за границу"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.post("/recommend", json={"query": query})
            initial_body = initial.json()
            destination = initial_body["recommendations"][0]["candidate"]
            first = await client.post(
                "/destination-chat",
                json={
                    "session_id": initial_body["session_id"],
                    "destination_id": destination["destination_id"],
                    "query": "Где лучше остановиться?",
                },
            )
            second = await client.post(
                "/destination-chat",
                json={
                    "session_id": initial_body["session_id"],
                    "destination_id": destination["destination_id"],
                    "query": "А что из этого ближе к интересным местам?",
                },
            )
            state = await app.state.resources.planner_graph.aget_state(
                {"configurable": {"thread_id": initial_body["session_id"]}}
            )

    assert first.status_code == 200
    assert first.json()["turn_index"] == 2
    assert first.json()["message_count"] == 2
    assert second.status_code == 200
    assert second.json()["turn_index"] == 3
    assert second.json()["message_count"] == 4
    stored_thread = state.values["destination_threads"][destination["destination_id"]]
    assert [message["role"] for message in stored_thread["messages"]] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    destination_traces = [
        record
        for record in recorder.records
        if record["type"] == "trace" and record["name"] == "destination_conversation"
    ]
    assert [trace["trace_name"] for trace in destination_traces] == [
        f"Turn 02 · destination question · {destination['city_or_region']}",
        f"Turn 03 · destination question · {destination['city_or_region']}",
    ]
    assert all(trace["session_id"] == initial_body["session_id"] for trace in destination_traces)
    assert destination_traces[0]["metadata"]["subthread_id"] == (
        f"destination:{destination['destination_id']}"
    )


@pytest.mark.asyncio
async def test_root_page_and_feedback_endpoint_work() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            page = await client.get("/")
            feedback = await client.post(
                "/feedback",
                json={
                    "session_id": "session-123",
                    "request_id": "request-123",
                    "destination_id": "batumi",
                    "value": "up",
                    "comment": "Полезно",
                },
            )
            travel_link = await client.post(
                "/events/travel-link",
                json={
                    "session_id": "session-123",
                    "request_id": "request-123",
                    "destination_id": "batumi",
                    "rank": 1,
                    "provider": "aviasales",
                    "link_kind": "flight",
                },
            )
            recorded_clicks = list(app.state.resources.product_event_store.travel_link_events)

    assert page.status_code == 200
    assert "Пора в путь" in page.text
    assert "AI travel copilot" in page.text
    assert "Живая подборка" in page.text
    assert feedback.status_code == 204
    assert travel_link.status_code == 204
    assert len(recorded_clicks) == 1
    assert recorded_clicks[0].destination_id == "batumi"
    assert recorded_clicks[0].provider == "aviasales"
