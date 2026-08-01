"""Typed container for resources built once during FastAPI lifespan."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.accounts.auth import AuthService
from app.accounts.store import AccountRepository
from app.core.config import Settings
from app.core.http_security import SlidingWindowRateLimiter
from app.observability.port import ObservabilityPort
from app.places.repository import PlacesRepository
from app.pricing.registry import PricingProviderRegistry
from app.services.events import ProductEventRepository
from app.services.feedback import FeedbackRepository
from app.services.model_gateway import ModelGateway
from app.services.workflow import PlannerGraph


@dataclass(slots=True)
class AppResources:
    """Long-lived resources are injected through the app, never graph state."""

    settings: Settings
    http_client: httpx.AsyncClient
    model_gateway: ModelGateway
    observability: ObservabilityPort
    planner_graph: PlannerGraph
    checkpointer: BaseCheckpointSaver[str]
    feedback_store: FeedbackRepository
    product_event_store: ProductEventRepository
    places_repository: PlacesRepository
    account_store: AccountRepository
    auth_service: AuthService
    pricing_providers: PricingProviderRegistry
    rate_limiter: SlidingWindowRateLimiter
    database_ready: bool
    checkpointer_ready: bool
