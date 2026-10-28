"""Lock the public MCP tool list and the Agensi skill package shape."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "strata-memory"

EXPECTED_TOOLS = [
    "strata_init",
    "commit_memory",
    "promote_session",
    "recall_context",
    "expand_memory_detail",
    "strata_doctor",
    "strata_rebuild_index",
    "strata_stats",
    "strata_project",
    "strata_digest",
    "strata_hygiene",
]


@pytest.mark.asyncio
async def test_list_tools_matches_documented_surface():
    from strata_memory.server import handle_list_tools

    tools = await handle_list_tools()
    assert [tool.name for tool in tools] == EXPECTED_TOOLS


def test_skill_package_is_agensi_shaped():
    skill_md = SKILL_DIR / "SKILL.md"
    text = skill_md.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = text.split("---", 2)[1]
    meta = yaml.safe_load(frontmatter)

    assert meta["name"] == "strata-memory"
    assert SKILL_DIR.name == meta["name"]
    assert "Use when" in meta["description"]
    assert len(meta["description"]) <= 1024
    assert len(meta["summary"]) <= 300
    for key in ("summary", "version", "tags", "keywords", "use_cases", "docs_url"):
        assert meta[key]
    assert meta["docs_url"] == "https://github.com/SherryLi-vc/strata-memory"
    assert meta["version"] == "1.0.0"
    assert "https://api.siliconflow.cn" in text
    assert "The configured embedding endpoint receives memory text" in text
    assert "only implemented embedding provider is SiliconFlow" not in text
    assert "uvx strata-memory-mcp" not in text
    assert "github.com/vincy/" not in text
    for tool in EXPECTED_TOOLS:
        assert f"`{tool}`" in text

    references = SKILL_DIR / "references"
    for name in (
        "claude-code.mcp.json",
        "cursor-mcp.json",
        "claude-desktop.json",
        "hermes-config.yaml",
    ):
        path = references / name
        assert path.is_file(), name
        assert path.name in text
        body = path.read_text(encoding="utf-8")
        assert "vizhangkk" not in body
        assert "/Users/" not in body
        assert "sk-" not in body.replace("sk-xxx...yyy", "")

    assert "Joeri" not in text
    for link in (ROOT / ".claude" / "skills" / "strata-memory", ROOT / ".hermes" / "skills" / "strata-memory"):
        assert link.is_symlink()
        assert (link / "SKILL.md").is_file()
        assert link.resolve() == SKILL_DIR.resolve()
