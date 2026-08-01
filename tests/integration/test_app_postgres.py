"""Optional contract checks against an explicitly isolated PostgreSQL test database."""

from __future__ import annotations

import os
from typing import TypedDict
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, START, StateGraph

DATABASE_URL = os.environ.get("APP_TEST_DATABASE_URL")


class PersistedState(TypedDict):
    value: str


async def _identity(state: PersistedState) -> PersistedState:
    return state


@pytest.mark.skipif(
    not DATABASE_URL, reason="APP_TEST_DATABASE_URL is required for PostgreSQL contract"
)
async def test_langgraph_checkpoint_survives_restart_and_thread_deletion() -> None:
    thread_id = f"test-{uuid4()}"
    config = {"configurable": {"thread_id": thread_id}}
    graph = StateGraph(PersistedState)
    graph.add_node("identity", _identity)
    graph.add_edge(START, "identity")
    graph.add_edge("identity", END)

    async with AsyncPostgresSaver.from_conn_string(str(DATABASE_URL)) as first:
        await first.setup()
        await graph.compile(checkpointer=first).ainvoke({"value": "survives"}, config)
    async with AsyncPostgresSaver.from_conn_string(str(DATABASE_URL)) as second:
        compiled = graph.compile(checkpointer=second)
        assert (await compiled.aget_state(config)).values["value"] == "survives"
        await second.adelete_thread(thread_id)
        assert not (await compiled.aget_state(config)).values
