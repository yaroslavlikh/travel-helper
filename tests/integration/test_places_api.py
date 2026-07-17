import httpx
import pytest

from app.core.config import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_places_search_reports_unconfigured_storage() -> None:
    app = create_app(
        Settings(
            app_env="test",
            demo_mode=True,
            langfuse_enabled=False,
            places_database_url=None,
            _env_file=None,
        )
    )

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/places/search", json={"destination": "istanbul"})

    assert response.status_code == 503
    assert response.json()["detail"] == "Places database is not configured"
