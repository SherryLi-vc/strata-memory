"""One version everywhere a user or a host can see it."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import strata_memory
from strata_memory.config import Config

ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]


def test_package_version_matches_pyproject():
    assert strata_memory.__version__ == _pyproject_version()


def test_new_config_records_package_version():
    assert Config().version == strata_memory.__version__


def test_changelog_top_entry_is_current_version():
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    top = re.search(r"^## \[([^\]]+)\]", text, re.MULTILINE)
    assert top and top.group(1) == _pyproject_version()


def test_no_hardcoded_server_or_init_versions():
    """Server handshake, strata_init and the CLI must report __version__, not a literal."""
    offenders = []
    for rel in ("strata_memory/server.py", "strata_memory/cli.py", "strata_memory/ops/migrate_v02.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for match in re.finditer(r'(server_version|version)\s*[=:]\s*"\d+\.\d+\.\d+"', src):
            offenders.append(f"{rel}: {match.group(0)}")
        for match in re.finditer(r'"version":\s*"\d+\.\d+\.\d+"', src):
            offenders.append(f"{rel}: {match.group(0)}")
    assert offenders == []


def test_skill_metadata_matches_package_version():
    skill = (ROOT / "skills/strata-memory/SKILL.md").read_text(encoding="utf-8")
    assert f'server_version: "{_pyproject_version()}"' in skill
    assert f"(v{_pyproject_version()}, MIT)" in skill
