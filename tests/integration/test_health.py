import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


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

    assert page.status_code == 200
    assert "Пора в путь" in page.text
    assert "AI travel copilot" in page.text
    assert "Живая подборка" in page.text
    assert feedback.status_code == 204
