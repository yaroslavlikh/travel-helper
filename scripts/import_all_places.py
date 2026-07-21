"""Import every bounded destination catalog scope, continuing after provider failures."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.core.config import Settings
from app.places.catalog import DESTINATIONS
from app.places.importer import (
    fetch_osm,
    import_osm_places,
    normalize_osm_payload,
    persist_raw_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fetch", action="store_true", help="Fetch current Overpass snapshots")
    parser.add_argument("--limit", type=int, default=250, choices=range(100, 301))
    parser.add_argument(
        "--destinations",
        help="Comma-separated catalog IDs; defaults to the complete catalog",
    )
    args = parser.parse_args()
    if not args.fetch:
        raise SystemExit(
            "Only --fetch is supported; use the single-destination command for a saved input."
        )
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")

    destination_ids = args.destinations.split(",") if args.destinations else list(DESTINATIONS)
    unknown = sorted(set(destination_ids) - set(DESTINATIONS))
    if unknown:
        raise SystemExit(f"Unsupported catalog destinations: {', '.join(unknown)}")

    reports: dict[str, object] = {}
    for destination_id in destination_ids:
        destination = DESTINATIONS[destination_id]
        try:
            payload = fetch_osm(destination.destination_id)
            raw_path, checksum = persist_raw_payload(
                payload,
                Path("data/raw") / destination.destination_id,
                destination=destination.destination_id,
            )
            records, rejected = normalize_osm_payload(payload, limit=args.limit)
            reports[destination.destination_id] = asdict(
                import_osm_places(
                    settings.places_database_url,
                    records,
                    checksum=checksum,
                    raw_path=raw_path,
                    embedding_version=settings.places_embedding_version,
                    rejected=Counter(rejected),
                    destination=destination,
                )
            )
        except Exception as error:  # keep the catalogue usable when one public scope fails
            reports[destination.destination_id] = {"error": str(error)}
    print(json.dumps(reports, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
