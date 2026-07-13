"""Validate repository-local Markdown links without network access."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LINK_PATTERN = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")


def is_external(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def validate_links() -> list[str]:
    """Return every broken local Markdown link as a human-readable error."""

    failures: list[str] = []
    for markdown_file in ROOT.rglob("*.md"):
        if ".git" in markdown_file.parts:
            continue
        content = markdown_file.read_text(encoding="utf-8")
        for target in LINK_PATTERN.findall(content):
            clean_target = target.split("#", maxsplit=1)[0]
            if not clean_target or is_external(target):
                continue
            if not (markdown_file.parent / clean_target).resolve().exists():
                failures.append(f"{markdown_file.relative_to(ROOT)}: missing link target {target}")
    return failures


def main() -> int:
    """Print validation failures and return a shell-friendly status code."""

    failures = validate_links()
    if failures:
        print("\n".join(failures))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
