from contextlib import contextmanager
from typing import Any
from urllib.parse import parse_qs, urlparse

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


class UnavailablePostgresPool:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    async def open(self, **_kwargs: object) -> None:
        raise OSError("database is unavailable")


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
            {"name": "flight_pricing", "status": "disabled"},
            {"name": "flight_cached_discovery", "status": "disabled"},
            {"name": "stay_pricing", "status": "disabled"},
        ],
    }


@pytest.mark.asyncio
async def test_staging_fails_startup_when_postgres_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.main.AsyncConnectionPool", UnavailablePostgresPool)
    app = create_app(
        Settings(
            app_env="staging",
            demo_mode=True,
            database_url="postgresql://unavailable.invalid/app",
            langfuse_enabled=False,
            _env_file=None,
        )
    )

    with pytest.raises(OSError, match="database is unavailable"):
        async with app.router.lifespan_context(app):
            pass


@pytest.mark.asyncio
async def test_public_http_guards_reject_unknown_hosts_and_limit_expensive_requests() -> None:
    app = create_app(
        Settings(
            app_env="test",
            demo_mode=True,
            trusted_hosts="allowed.test",
            rate_limit_requests=1,
            rate_limit_window_seconds=60,
            langfuse_enabled=False,
            _env_file=None,
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://blocked.test") as client:
            blocked = await client.get("/")
        async with httpx.AsyncClient(transport=transport, base_url="http://allowed.test") as client:
            first = await client.post("/recommend", json={"query": "Хочу в отпуск"})
            limited = await client.post("/recommend", json={"query": "Хочу в отпуск"})

    assert blocked.status_code == 400
    assert first.status_code == 200
    assert first.headers["x-content-type-options"] == "nosniff"
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "60"
    assert limited.headers["x-content-type-options"] == "nosniff"


@pytest.mark.asyncio
async def test_readiness_reports_missing_live_pricing_credentials_without_secrets() -> None:
    app = create_app(
        Settings(
            app_env="test",
            demo_mode=True,
            flight_provider_mode="live",
            stay_provider_mode="live",
            langfuse_enabled=False,
            _env_file=None,
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            live = await client.get("/health/live")
            ready = await client.get("/health/ready")
            providers = await client.get("/internal/provider-status")

    assert live.json() == {"status": "ok"}
    assert ready.json()["status"] == "degraded"
    assert ready.json()["components"]["flight_pricing"] == "missing_credentials"
    assert ready.json()["components"]["flight_cached_discovery"] == "disabled"
    assert ready.json()["components"]["stay_pricing"] == "missing_credentials"
    assert {item["name"]: item["status"] for item in providers.json()} == {
        "flight_pricing": "missing_credentials",
        "flight_cached_discovery": "disabled",
        "stay_pricing": "missing_credentials",
    }


@pytest.mark.asyncio
async def test_readiness_exposes_configured_cached_flight_discovery_without_a_live_claim() -> None:
    app = create_app(
        Settings(
            app_env="test",
            demo_mode=True,
            flight_provider_mode="cached",
            pricing_cached_enabled=True,
            travelpayouts_api_token="test-token",
            langfuse_enabled=False,
            _env_file=None,
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            ready = await client.get("/health/ready")
            providers = await client.get("/internal/provider-status")

    assert ready.json()["status"] == "degraded"
    assert ready.json()["components"]["flight_cached_discovery"] == "ready"
    assert {item["name"]: item["mode"] for item in providers.json()}[
        "flight_cached_discovery"
    ] == "cached"


@pytest.mark.asyncio
async def test_frontend_exposes_an_accessible_sidebar_collapse_control() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/")
            asset = await client.get("/static/app.js")

    assert response.status_code == 200
    assert 'id="sidebar-toggle"' in response.text
    assert 'aria-controls="chat-history"' in response.text
    assert "emrldtp.com/NTU3MzU1.js?t=557355" in response.text
    assert asset.headers["cache-control"] == "no-store, max-age=0"
    assert asset.headers["content-length"] == str(len(asset.content))


@pytest.mark.asyncio
async def test_recommendation_clarifies_then_resumes_same_session() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Хочу на море в августе на 7–10 дней, 150 тысяч на одного, без жары"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            clarification = await client.post("/recommend", json={"query": query})
            initial_body = clarification.json()
            resumed = await client.post(
                "/recommend",
                json={
                    "query": "Вылетаю из Москвы",
                    "session_id": initial_body["session_id"],
                },
            )

    assert clarification.status_code == 200
    assert initial_body["status"] == "needs_clarification"
    assert [question["field"] for question in initial_body["questions"]] == ["origin_city"]
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["turn_kind"] == "clarification"
    assert resumed.json()["parsed_request"]["origin_city"] == "Москва"
    assert len(resumed.json()["recommendations"]) >= 3
    pricing = resumed.json()["recommendations"][0]["pricing"]
    assert pricing["status"] == "unavailable"
    assert pricing["expected_total_rub"] is None
    assert [item["component"] for item in pricing["components"]] == ["flight", "stay"]
    assert all(item["status"] == "missing" for item in pricing["components"])
    assert resumed.json()["next_best_question"] is not None
    assert "Хотите сузить выбор" in resumed.json()["assistant_message"]


@pytest.mark.asyncio
async def test_free_text_reply_can_answer_origin_and_exact_trip_dates_together() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.post("/recommend", json={"query": "Хочу в отпуск"})
            resumed = await client.post(
                "/recommend",
                json={
                    "query": "Вылетаю из Москвы, хочу поехать с 20 августа по 3 сентября",
                    "session_id": initial.json()["session_id"],
                },
            )

    assert resumed.status_code == 200
    body = resumed.json()
    assert body["status"] == "completed"
    assert body["parsed_request"]["origin_city"] == "Москва"
    assert body["parsed_request"]["date_from"] == "2026-08-20"
    assert body["parsed_request"]["date_to"] == "2026-09-03"


@pytest.mark.asyncio
async def test_advisory_answer_refines_a_completed_shortlist() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.post(
                "/recommend",
                json={"query": "Хочу отдохнуть из Москвы"},
            )
            initial_body = initial.json()
            refined = await client.post(
                "/recommend",
                json={
                    "query": "География: за границу",
                    "session_id": initial_body["session_id"],
                    "answers": {"destination_scope": "international"},
                },
            )

    assert initial.status_code == 200
    assert initial_body["status"] == "completed"
    assert refined.status_code == 200
    assert refined.json()["status"] == "completed"
    assert refined.json()["turn_kind"] == "refinement"
    assert refined.json()["parsed_request"]["destination_scope"] == "international"


@pytest.mark.asyncio
async def test_invalid_legacy_structured_value_does_not_return_a_server_error() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            initial = await client.post(
                "/recommend",
                json={"query": "Хочу поехать из Москвы"},
            )
            refined = await client.post(
                "/recommend",
                json={
                    "query": "Виза: только шенген",
                    "session_id": initial.json()["session_id"],
                    "answers": {"visa_willingness": "тока шенген если"},
                },
            )

    assert refined.status_code == 200
    assert refined.json()["status"] == "completed"
    assert refined.json()["parsed_request"]["visa_willingness"] == "visa_ok"
    assert "шенгенская зона" in refined.json()["parsed_request"]["preferences"]


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
    assert root["updates"][-1]["output"]["question_count"] == 1
    assert clarification["updates"][-1]["output"] == {
        "status": "waiting_for_user",
        "question_fields": ["origin_city"],
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
            frontend = await client.get("/static/app.js")
            login_page = await client.get("/login")
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
    assert frontend.status_code == 200
    assert "Почему цена недоступна" in frontend.text
    assert "async function accountFetch" in frontend.text
    assert "await refreshAccountState()" in frontend.text
    assert "Тудавай" in page.text
    assert "Скажите, какого отдыха хочется" in page.text
    assert "Живая подборка" in page.text
    assert 'aria-controls="chat-view" aria-selected="true"' in page.text
    assert 'aria-controls="feed-panel" aria-selected="false"' in page.text
    assert "/static/app.js?v=20260803-origin-static" in page.text
    assert login_page.status_code == 200
    assert "Продолжайте с того места" in login_page.text
    assert "Вся поездка — в одном диалоге" in login_page.text
    assert 'id="password-form"' in login_page.text
    assert feedback.status_code == 204
    assert travel_link.status_code == 204
    assert len(recorded_clicks) == 1
    assert recorded_clicks[0].destination_id == "batumi"
    assert recorded_clicks[0].provider == "aviasales"


@pytest.mark.asyncio
async def test_card_flight_link_keeps_month_only_request_flexible() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Из Москвы на море в августе на неделю, 180 тысяч на одного, за границу"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/recommend", json={"query": query})

    body = response.json()
    links = body["recommendations"][0]["candidate"]["external_links"]
    flight_link = next(link for link in links if link["category"] == "flight")
    assert flight_link["provider"] == "aviasales"
    assert flight_link["title"] == "Выбрать даты"
    assert urlparse(flight_link["url"]).path.startswith("/routes/mow/")
    assert parse_qs(urlparse(flight_link["url"]).query) == {}


@pytest.mark.asyncio
async def test_card_flight_link_sends_exact_dates_and_passengers() -> None:
    app = create_app(
        Settings(app_env="test", demo_mode=True, langfuse_enabled=False, _env_file=None)
    )
    query = "Из Москвы за границу с 20 августа по 3 сентября, нас двое"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/recommend", json={"query": query})

    body = response.json()
    links = body["recommendations"][0]["candidate"]["external_links"]
    flight_link = next(link for link in links if link["category"] == "flight")
    parsed = urlparse(flight_link["url"])
    params = parse_qs(parsed.query)

    assert parsed.path == "/search"
    assert params["depart_date"] == ["2026-08-20"]
    assert params["return_date"] == ["2026-09-03"]
    assert params["adults"] == ["2"]
