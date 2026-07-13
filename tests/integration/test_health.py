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
