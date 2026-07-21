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
    if len(cases) < 40:
        raise RuntimeError(
            "The Istanbul evaluation set must contain at least 40 independent queries"
        )
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
                exclude_categories=case.get("forbidden_categories", []),
                limit=10,
            )
        )
        categories = [result.category for result in response.results if result.category]
        expected = set(case["expected_categories"])
        expected_names = (
            [value.casefold() for value in case.get("expected_names", [])]
            if case.get("name_recall")
            else []
        )
        names = [result.name for result in response.results]
        name_hit = any(
            expected_name in result.name.casefold()
            for expected_name in expected_names
            for result in response.results[:5]
        )
        category_hit = bool(expected.intersection(categories[:5]))
        forbidden = set(case.get("forbidden_categories", []))
        outcomes.append(
            {
                "query": case["query"],
                "result_count": len(response.results),
                "names": names,
                "categories": categories,
                "name_hit": name_hit if expected_names else None,
                "category_hit": category_hit,
                "forbidden_hit": bool(forbidden.intersection(categories[:5])),
                "passed": bool(response.results)
                and category_hit
                and not bool(forbidden.intersection(categories[:5])),
            }
        )
    passed = sum(item["passed"] for item in outcomes)
    named_cases = [item for item in outcomes if item["name_hit"] is not None]
    name_hits = sum(bool(item["name_hit"]) for item in named_cases)
    return {
        "dataset": str(EVALS_PATH.relative_to(EVALS_PATH.parents[2])),
        "query_count": len(outcomes),
        "passed": passed,
        "top5_category_recall": round(
            sum(bool(item["category_hit"]) for item in outcomes) / len(outcomes), 4
        ),
        "top5_name_recall": round(name_hits / len(named_cases), 4) if named_cases else None,
        "passed_recall": round(passed / len(outcomes), 4),
        "top_k_errors": [item for item in outcomes if not item["passed"]][:10],
        "outcomes": outcomes,
    }


def main() -> None:
    print(json.dumps(asyncio.run(evaluate()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
