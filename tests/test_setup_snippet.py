"""Host snippets for uvx strata-memory stay offline and contain no secrets."""

from __future__ import annotations

import pytest

from strata_memory.ops.setup_host import render_setup


@pytest.mark.parametrize("host", ["cursor", "claude-code", "claude-desktop"])
def test_setup_snippet_is_local_uvx(host):
    text = render_setup(host)
    assert "uvx" in text
    assert "strata-memory" in text
    assert '"STRATA_EMBEDDING_PROVIDER": "local"' in text
    assert "sk-" not in text
    assert "api.siliconflow.cn" not in text
