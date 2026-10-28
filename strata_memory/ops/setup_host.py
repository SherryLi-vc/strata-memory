"""Print an MCP host snippet that runs ``uvx strata-memory`` offline.

No API key is included. Cloud embedding stays an explicit opt-in.
"""

from __future__ import annotations

from typing import Literal, assert_never

HostName = Literal["cursor", "claude-code", "claude-desktop"]

_CURSOR = """\
{
  "mcpServers": {
    "strata-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["strata-memory"],
      "env": {
        "STRATA_PALACE": "${userHome}/.strata/palace",
        "STRATA_EMBEDDING_PROVIDER": "local"
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
      "args": ["strata-memory"],
      "env": {
        "STRATA_PALACE": "${STRATA_PALACE:-~/.strata/palace}",
        "STRATA_EMBEDDING_PROVIDER": "local"
      }
    }
  }
}
"""

_CLAUDE_DESKTOP = """\
# Claude Desktop does not expand ${VAR}. Replace the palace path if needed.
# If uvx is not on the app PATH, set command to the absolute uvx binary.
{
  "mcpServers": {
    "strata-memory": {
      "command": "uvx",
      "args": ["strata-memory"],
      "env": {
        "STRATA_PALACE": "~/.strata/palace",
        "STRATA_EMBEDDING_PROVIDER": "local"
      }
    }
  }
}
"""


def render_setup(host: HostName) -> str:
    """Return the snippet for one supported host."""
    if host == "cursor":
        return _CURSOR
    if host == "claude-code":
        return _CLAUDE_CODE
    if host == "claude-desktop":
        return _CLAUDE_DESKTOP
    assert_never(host)
