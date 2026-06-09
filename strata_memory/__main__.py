"""Entry point for `python -m strata_memory` and `strata-memory-mcp` CLI."""

import asyncio
from .server import run


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
