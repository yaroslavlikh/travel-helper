"""Small structured logging setup with no secret-bearing configuration dump."""

from __future__ import annotations

import logging


def configure_logging(level: str) -> None:
    """Configure predictable process logging once during application startup."""

    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        force=True,
    )
