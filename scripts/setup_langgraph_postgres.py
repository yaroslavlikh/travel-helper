"""Create or upgrade LangGraph checkpoint tables without touching application data."""

from __future__ import annotations

import asyncio

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.core.config import Settings


async def setup(database_url: str) -> None:
    async with AsyncPostgresSaver.from_conn_string(database_url) as checkpointer:
        await checkpointer.setup()


def main() -> None:
    settings = Settings()
    if not settings.database_url_value:
        raise SystemExit("DATABASE_URL is required")
    asyncio.run(setup(settings.database_url_value))
    print("LangGraph PostgreSQL checkpoint tables are ready")


if __name__ == "__main__":
    main()
