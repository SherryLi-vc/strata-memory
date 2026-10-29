"""Print an MCP host snippet that runs strata-memory-mcp through ``uvx``.

Until the package is on PyPI the snippet installs from git (``GIT_SOURCE``).
After the first PyPI release, switch the args back to ``["strata-memory-mcp"]``.

The snippet does not set ``STRATA_EMBEDDING_PROVIDER``. An environment value
overrides ``config.json``, so hard-coding ``local`` would silently retarget
an existing SiliconFlow palace onto a different embedder at the same dimension.

``uvx strata-memory`` is a different PyPI project. Do not use that name.
"""

from __future__ import annotations

from typing import Literal, assert_never

HostName = Literal["cursor", "claude-code", "claude-desktop"]

GIT_SOURCE = "git+https://github.com/SherryLi-vc/strata-memory"

_CURSOR = """\
{
  "mcpServers": {
    "strata-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SherryLi-vc/strata-memory", "strata-memory-mcp"],
      "env": {
        "STRATA_PALACE": "${userHome}/.strata/palace"
      }
    }
  }
}
"""

_CLAUDE_CODE = """\
{
  "mcpServers": {
    "strata-memory": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SherryLi-vc/strata-memory", "strata-memory-mcp"],
      "env": {
        "STRATA_PALACE": "${STRATA_PALACE:-~/.strata/palace}"
      }
    }
  }
}
"""

_CLAUDE_DESKTOP = """\
{
  "mcpServers": {
    "strata-memory": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SherryLi-vc/strata-memory", "strata-memory-mcp"],
      "env": {
        "STRATA_PALACE": "~/.strata/palace"
      }
    }
  }
}
"""


def render_setup(host: HostName) -> str:
    """Return the snippet for one supported host. The text is JSON."""
    if host == "cursor":
        return _CURSOR
    if host == "claude-code":
        return _CLAUDE_CODE
    if host == "claude-desktop":
        return _CLAUDE_DESKTOP
    assert_never(host)
