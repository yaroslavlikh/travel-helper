"""FastAPI application entrypoint and lifecycle resource composition."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.api.routes import router as recommendation_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.resources import AppResources
from app.observability.langfuse import create_observability
from app.observability.port import ObservabilityPort
from app.services.events import ProductEventStore
from app.services.feedback import FeedbackStore
from app.services.model_gateway import create_model_gateway
from app.services.workflow import build_planner_graph


class ProviderHealth(BaseModel):
    """Public-safe provider status; never includes credentials or internal endpoints."""

    name: str
    status: Literal["configured", "disabled", "deferred"]


class HealthResponse(BaseModel):
    """Readiness response for humans, deployment checks, and the future UI."""

    status: Literal["ok", "degraded"]
    environment: Literal["development", "test", "production"]
    mode: Literal["demo", "configured"]
    version: str
    providers: list[ProviderHealth]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create an application instance, allowing isolated settings in tests."""

    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.log_level)
        async with AsyncExitStack() as stack:
            http_client = httpx.AsyncClient(timeout=httpx.Timeout(15.0))
            observability: ObservabilityPort = create_observability(resolved_settings)
            model_gateway = create_model_gateway(
                resolved_settings,
                observability=observability,
            )
            checkpointer: BaseCheckpointSaver[str]
            if resolved_settings.app_env == "test":
                checkpointer = InMemorySaver()
            else:
                checkpoint_path = Path(resolved_settings.checkpoint_db_path)
                checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
                sqlite_checkpointer = await stack.enter_async_context(
                    AsyncSqliteSaver.from_conn_string(str(checkpoint_path))
                )
                await sqlite_checkpointer.setup()
                checkpointer = sqlite_checkpointer
            app.state.resources = AppResources(
                settings=resolved_settings,
                http_client=http_client,
                model_gateway=model_gateway,
                observability=observability,
                planner_graph=build_planner_graph(
                    checkpointer=checkpointer,
                    observability=observability,
                    model_gateway=model_gateway,
                    demo_mode=resolved_settings.demo_mode,
                ),
                feedback_store=FeedbackStore(),
                product_event_store=ProductEventStore(),
            )
            try:
                yield
            finally:
                await model_gateway.aclose()
                observability.shutdown()
                await http_client.aclose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    static_directory = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_directory), name="static")
    app.include_router(recommendation_router)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health(request: Request) -> HealthResponse:
        resources = cast(AppResources, request.app.state.resources)
        model_status: Literal["configured", "disabled", "deferred"] = (
            "configured" if resources.settings.model_is_configured else "disabled"
        )
        observability_status: Literal["configured", "disabled", "deferred"] = (
            "configured" if resources.observability.backend_name == "langfuse" else "deferred"
        )
        mode: Literal["demo", "configured"] = (
            "demo" if resources.settings.demo_mode else "configured"
        )
        overall: Literal["ok", "degraded"] = "ok" if mode == "configured" else "degraded"
        return HealthResponse(
            status=overall,
            environment=resources.settings.app_env,
            mode=mode,
            version=resources.settings.app_version,
            providers=[
                ProviderHealth(name="llm", status=model_status),
                ProviderHealth(
                    name=resources.observability.backend_name, status=observability_status
                ),
            ],
        )

    return app


app = create_app()
