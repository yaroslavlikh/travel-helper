"""Minimal state types shared by the first LangGraph vertical slice."""

from __future__ import annotations

from typing import Literal, TypedDict


class PlannerState(TypedDict, total=False):
    """JSON-serializable checkpoint state; runtime clients never enter this object."""

    request_id: str
    session_id: str
    status: Literal["received", "ready"]
    warnings: list[str]
