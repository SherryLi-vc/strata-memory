"""Entry point for `strata-memory` and `strata-memory-mcp`.

`uvx strata-memory` starts the MCP server. Subcommands (setup, export, …)
are handled by the CLI. `strata-memory-mcp` always serves, so existing host
configs keep working.
"""

import asyncio
import sys
from pathlib import Path

from .cli import main as cli_main
from .server import run

_CLI_COMMANDS = {
    "init",
    "doctor",
    "stats",
    "digest",
    "project",
    "migrate",
    "serve",
    "setup",
    "export",
    "help",
    "--help",
    "-h",
}


def main() -> None:
    argv0 = Path(sys.argv[0]).name.lower()
    if "strata-memory-mcp" in argv0:
        asyncio.run(run())
        return
    if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:
        cli_main()
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
