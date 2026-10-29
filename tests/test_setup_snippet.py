"""Host snippets (uvx from git until PyPI) do not override a saved embedder."""

from __future__ import annotations

import json

import pytest

from strata_memory.ops.setup_host import render_setup


@pytest.mark.parametrize("host", ["cursor", "claude-code", "claude-desktop"])
def test_setup_snippet_is_json_and_does_not_pin_provider(host):
    text = render_setup(host)
    parsed = json.loads(text)
    args = parsed["mcpServers"]["strata-memory"]["args"]
    env = parsed["mcpServers"]["strata-memory"]["env"]
    assert args == ["--from", "git+https://github.com/SherryLi-vc/strata-memory", "strata-memory-mcp"]
    assert "STRATA_EMBEDDING_PROVIDER" not in env
    assert "sk-" not in text
    assert text.strip().startswith("{")
