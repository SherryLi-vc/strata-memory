"""Until the package is on PyPI, every install command users copy must use the git source."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from strata_memory.ops.setup_host import GIT_SOURCE, render_setup

ROOT = Path(__file__).resolve().parents[1]
DOCS = ["README.md", "README.zh-CN.md", "skills/strata-memory/SKILL.md", "DEVELOPMENT.md", "docs/tools.md"]
SNIPPETS = [
    "skills/strata-memory/references/cursor-mcp.json",
    "skills/strata-memory/references/claude-code.mcp.json",
    "skills/strata-memory/references/claude-desktop.json",
    "examples/cursor-mcp.json",
]
GIT_ARGS = ["--from", GIT_SOURCE, "strata-memory-mcp"]
# A bare PyPI invocation, e.g. "uvx strata-memory-mcp" or "-- uvx strata-memory-mcp setup".
BARE_PYPI = re.compile(r"uvx\s+(?:--from\s+'strata-memory-mcp\[local\]'\s+)?strata-memory-mcp\b")


def test_git_source_points_at_the_repo():
    assert GIT_SOURCE == "git+https://github.com/SherryLi-vc/strata-memory"


@pytest.mark.parametrize("host", ["cursor", "claude-code", "claude-desktop"])
def test_setup_snippets_install_from_git(host):
    args = json.loads(render_setup(host))["mcpServers"]["strata-memory"]["args"]
    assert args == GIT_ARGS


@pytest.mark.parametrize("rel", SNIPPETS)
def test_shipped_snippet_files_install_from_git(rel):
    server = json.loads((ROOT / rel).read_text(encoding="utf-8"))["mcpServers"]["strata-memory"]
    assert server["command"] == "uvx"
    assert server["args"] == GIT_ARGS


@pytest.mark.parametrize("rel", DOCS)
def test_docs_have_no_bare_pypi_command_outside_the_coming_soon_note(rel):
    path = ROOT / rel
    if not path.exists():
        pytest.skip(rel)
    offenders = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if BARE_PYPI.search(line) and not re.search(r"coming soon|即将上线", line, re.IGNORECASE):
            offenders.append(line.strip())
    assert offenders == []


@pytest.mark.parametrize("rel,marker", [("README.md", "coming soon"), ("README.zh-CN.md", "即将上线")])
def test_readme_marks_pypi_install_as_coming_soon(rel, marker):
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert marker in text
    quickstart = text.split("```bash", 1)[1].split("```", 1)[0]
    assert GIT_SOURCE in quickstart


def _registered_tools() -> list[str]:
    src = (ROOT / "strata_memory/server.py").read_text(encoding="utf-8")
    block = src.split("async def handle_list_tools", 1)[1].split("@server.", 1)[0]
    return re.findall(r'Tool\(\s*name="([a-z_]+)"', block)


def test_registered_tool_count_is_13():
    assert len(_registered_tools()) == 13


@pytest.mark.parametrize(
    "rel,pattern",
    [
        ("README.md", r"## Tools \(13\)"),
        ("README.zh-CN.md", r"## 工具（13 个）"),
        ("skills/strata-memory/SKILL.md", r"## Tools \(13\)"),
        ("DEVELOPMENT.md", r"\(13 tools\)"),
    ],
)
def test_docs_state_13_tools(rel, pattern):
    assert re.search(pattern, (ROOT / rel).read_text(encoding="utf-8"))


@pytest.mark.parametrize("rel", ["README.md", "README.zh-CN.md", "skills/strata-memory/SKILL.md"])
def test_tool_tables_list_every_registered_tool(rel):
    text = (ROOT / rel).read_text(encoding="utf-8")
    for name in _registered_tools():
        assert f"`{name}`" in text, name
