"""Entry point for the ``strata-memory-mcp`` command.

No arguments starts the MCP server. ``setup``, ``export``, ``--help``, and the
other subcommands go to the CLI. The PyPI distribution name is
``strata-memory-mcp``. ``uvx strata-memory`` is a different package.
"""

import asyncio
import sys

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
    if len(sys.argv) > 1 and sys.argv[1] in _CLI_COMMANDS:
        cli_main()
        return
    asyncio.run(run())


if __name__ == "__main__":
    main()
