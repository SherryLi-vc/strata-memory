#!/usr/bin/env python3
"""Fail a release when the tag, pyproject version, and package __version__ disagree.

python scripts/check_release_version.py [TAG]
TAG may be "v2.2.1" or "2.2.1". Without a tag only pyproject vs __version__ is checked.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path


def check(root: Path, tag: str = "") -> list[str]:
    errors: list[str] = []
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    init = (root / "strata_memory" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'^__version__\s*=\s*"([^"]+)"', init, re.MULTILINE)
    package = match.group(1) if match else ""
    if package != project:
        errors.append(f"strata_memory.__version__={package!r} != pyproject version {project!r}")
    if tag:
        wanted = tag[1:] if tag.startswith("v") else tag
        if wanted != project:
            errors.append(f"tag {tag!r} does not match pyproject version {project!r}")
    return errors


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    tag = sys.argv[1] if len(sys.argv) > 1 else ""
    errors = check(root, tag)
    for err in errors:
        print(f"::error::{err}")
    if errors:
        raise SystemExit(1)
    print("release version ok")


if __name__ == "__main__":
    main()
