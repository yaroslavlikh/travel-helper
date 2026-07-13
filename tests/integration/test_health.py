import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_health_exposes_safe_demo_status() -> None:
    app = create_app(Settings(app_env="test", demo_mode=True))

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
    app = create_app(Settings(app_env="test", demo_mode=True))
    query = "Из Москвы на море в августе на 7–10 дней, 150 тысяч на одного, без жары"

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            clarification = await client.post("/recommend", json={"query": query})
            initial_body = clarification.json()
            resumed = await client.post(
                "/recommend",
                json={
                    "query": query,
                    "session_id": initial_body["session_id"],
                    "answers": {"destination_scope": "international"},
                },
            )

    assert clarification.status_code == 200
    assert initial_body["status"] == "needs_clarification"
    assert [question["field"] for question in initial_body["questions"]] == ["destination_scope"]
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "completed"
    assert resumed.json()["parsed_request"]["destination_scope"] == "international"
    assert len(resumed.json()["recommendations"]) >= 3
