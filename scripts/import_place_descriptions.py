"""Import reviewed, attributed POI description manifests without fetching the web."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.core.config import Settings
from app.core.logging import configure_logging
from app.places.descriptions import import_place_descriptions, load_description_manifest


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Import a reviewed POI description manifest into the canonical places database"
    )
    parser.add_argument("--input", required=True, type=Path, help="Reviewed JSON manifest path")
    args = parser.parse_args()
    settings = Settings()
    configure_logging(settings.log_level)
    if not settings.places_database_url:
        raise SystemExit("PLACES_DATABASE_URL is required")
    manifest = load_description_manifest(args.input)
    report = import_place_descriptions(
        settings.places_database_url,
        manifest,
        manifest_path=args.input,
        embedding_version=settings.places_embedding_version,
    )
    print(json.dumps(report.as_dict(), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
