"""FastAPI application entrypoint and lifecycle resource composition."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal, cast

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from app.accounts.auth import AuthService
from app.accounts.routes import router as account_router
from app.accounts.store import AccountStore
from app.api.routes import router as recommendation_router
from app.core.config import Settings, get_settings
from app.core.http_security import SlidingWindowRateLimiter, security_headers
from app.core.logging import configure_logging
from app.core.resources import AppResources
from app.observability.langfuse import create_observability
from app.observability.port import ObservabilityPort
from app.places.repository import create_places_repository
from app.pricing.registry import PricingProviderStatus, create_pricing_provider_registry
from app.services.events import ProductEventStore
from app.services.feedback import FeedbackStore
from app.services.model_gateway import create_model_gateway
from app.services.workflow import build_planner_graph


class ProviderHealth(BaseModel):
    """Public-safe provider status; never includes credentials or internal endpoints."""

    name: str
    status: Literal[
        "configured",
        "disabled",
        "deferred",
        "fixture",
        "missing_credentials",
        "not_implemented",
        "ready",
    ]


class ReadyResponse(BaseModel):
    """Safe readiness status for staging and provider verification."""

    status: Literal["ready", "degraded"]
    components: dict[str, str]


class HealthResponse(BaseModel):
    """Readiness response for humans, deployment checks, and the future UI."""

    status: Literal["ok", "degraded"]
    environment: Literal["development", "test", "staging", "production"]
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
                checkpointer=checkpointer,
                feedback_store=FeedbackStore(),
                product_event_store=ProductEventStore(),
                places_repository=create_places_repository(
                    resolved_settings.places_database_url,
                    resolved_settings.places_embedding_version,
                ),
                account_store=(
                    account_store := AccountStore(
                        ":memory:"
                        if resolved_settings.app_env == "test"
                        else resolved_settings.account_db_path
                    )
                ),
                auth_service=AuthService(
                    settings=resolved_settings,
                    store=account_store,
                    http_client=http_client,
                ),
                pricing_providers=create_pricing_provider_registry(resolved_settings),
                rate_limiter=SlidingWindowRateLimiter(
                    max_requests=resolved_settings.rate_limit_requests,
                    window_seconds=resolved_settings.rate_limit_window_seconds,
                ),
            )
            try:
                yield
            finally:
                account_store.close()
                await model_gateway.aclose()
                observability.shutdown()
                await http_client.aclose()

    app = FastAPI(
        title=resolved_settings.app_name,
        version=resolved_settings.app_version,
        lifespan=lifespan,
    )
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=list(resolved_settings.trusted_host_list)
    )
    if resolved_settings.cors_allowed_origin_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(resolved_settings.cors_allowed_origin_list),
            allow_credentials=True,
            allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    expensive_paths = {
        "/recommend",
        "/destination-chat",
        "/auth/password/register",
        "/auth/password/login",
    }

    @app.middleware("http")
    async def apply_public_http_guards(request: Request, call_next):  # type: ignore[no-untyped-def]
        response_headers = security_headers(production=resolved_settings.app_env == "production")
        resources = getattr(request.app.state, "resources", None)
        if (
            isinstance(resources, AppResources)
            and resources.settings.rate_limit_enabled
            and request.method == "POST"
            and request.url.path in expensive_paths
        ):
            client_ip = request.client.host if request.client else "unknown"
            retry_after = resources.rate_limiter.retry_after_seconds(
                f"{request.url.path}:{client_ip}"
            )
            if retry_after is not None:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again shortly."},
                    headers={**response_headers, "Retry-After": str(retry_after)},
                )
        response = await call_next(request)
        for header, value in response_headers.items():
            response.headers.setdefault(header, value)
        return response

    static_directory = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=static_directory), name="static")
    app.include_router(recommendation_router)
    app.include_router(account_router)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @app.get("/login", include_in_schema=False)
    async def login_page() -> FileResponse:
        return FileResponse(static_directory / "login.html")

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
                *[
                    ProviderHealth(name=item.name, status=item.status)
                    for item in resources.pricing_providers.public_statuses()
                ],
            ],
        )

    @app.get("/health/live", tags=["system"])
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", response_model=ReadyResponse, tags=["system"])
    async def ready(request: Request) -> ReadyResponse:
        resources = cast(AppResources, request.app.state.resources)
        pricing = resources.pricing_providers.public_statuses()
        components: dict[str, str] = {
            "checkpointer": "ready",
            "llm": "ready" if resources.settings.model_is_configured else "disabled",
            **{item.name: item.status for item in pricing},
        }
        return ReadyResponse(
            status="ready" if resources.pricing_providers.is_ready else "degraded",
            components=components,
        )

    @app.get("/internal/provider-status", tags=["internal"], include_in_schema=False)
    async def provider_status(request: Request) -> list[PricingProviderStatus]:
        resources = cast(AppResources, request.app.state.resources)
        if resources.settings.app_env == "production":
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="Not found")
        return list(resources.pricing_providers.public_statuses())

    return app


app = create_app()
