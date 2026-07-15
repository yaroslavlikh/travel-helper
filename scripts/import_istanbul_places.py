"""Fetch and import one bounded, repeatable Istanbul OSM places snapshot."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.core.config import Settings
from app.places.importer import (
    fetch_istanbul_osm,
    import_osm_places,
    normalize_osm_payload,
    persist_raw_payload,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fetch", action="store_true", help="Fetch a new public OSM/Overpass snapshot"
    )
    parser.add_argument("--input", type=Path, help="Reuse an already saved raw OSM JSON file")
    parser.add_argument("--limit", type=int, default=250, choices=range(100, 301))
    args = parser.parse_args()
    if args.fetch == bool(args.input):
        raise SystemExit("Provide exactly one of --fetch or --input")
    settings = Settings()
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    raw_directory = Path("data/raw/istanbul")
    payload = (
        fetch_istanbul_osm() if args.fetch else json.loads(args.input.read_text(encoding="utf-8"))
    )
    raw_path, checksum = persist_raw_payload(payload, raw_directory)
    records, rejected = normalize_osm_payload(payload, limit=args.limit)
    report = import_osm_places(
        settings.places_database_url,
        records,
        checksum=checksum,
        raw_path=raw_path,
        embedding_version=settings.places_embedding_version,
        rejected=Counter(rejected),
    )
    print(json.dumps(asdict(report), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
