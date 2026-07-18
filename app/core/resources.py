"""Typed container for resources built once during FastAPI lifespan."""

from __future__ import annotations

from dataclasses import dataclass

import httpx
from langgraph.checkpoint.base import BaseCheckpointSaver

from app.accounts.auth import AuthService
from app.accounts.store import AccountStore
from app.core.config import Settings
from app.observability.port import ObservabilityPort
from app.places.repository import PlacesRepository
from app.services.events import ProductEventStore
from app.services.feedback import FeedbackStore
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
    feedback_store: FeedbackStore
    product_event_store: ProductEventStore
    places_repository: PlacesRepository
    account_store: AccountStore
    auth_service: AuthService
