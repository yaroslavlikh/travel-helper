"""Run the fixed Istanbul retrieval evaluation set against the local places API store."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.core.config import Settings
from app.places.models import PlaceSearchQuery
from app.places.repository import PostgresPlacesRepository

EVALS_PATH = Path(__file__).resolve().parents[1] / "data" / "evals" / "istanbul_places_queries.json"


async def evaluate() -> dict[str, Any]:
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    cases = json.loads(EVALS_PATH.read_text(encoding="utf-8"))
    if len(cases) != 30:
        raise RuntimeError("The Istanbul evaluation set must contain exactly 30 queries")
    repository = PostgresPlacesRepository(
        database_url=settings.places_database_url,
        embedding_version=settings.places_embedding_version,
    )
    outcomes: list[dict[str, Any]] = []
    for case in cases:
        response = await repository.search(
            PlaceSearchQuery(
                destination="istanbul",
                query=case["query"],
                budget=case.get("budget", "any"),
                indoor=case.get("indoor"),
                limit=10,
            )
        )
        categories = [result.category for result in response.results if result.category]
        expected = set(case["expected_categories"])
        outcomes.append(
            {
                "query": case["query"],
                "result_count": len(response.results),
                "categories": categories,
                "passed": bool(response.results) and bool(expected.intersection(categories[:5])),
            }
        )
    passed = sum(item["passed"] for item in outcomes)
    return {
        "dataset": str(EVALS_PATH.relative_to(EVALS_PATH.parents[2])),
        "query_count": len(outcomes),
        "passed": passed,
        "top5_category_recall": round(passed / len(outcomes), 4),
        "outcomes": outcomes,
    }


def main() -> None:
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
