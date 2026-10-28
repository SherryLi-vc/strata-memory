#!/usr/bin/env python3
"""MCP initialize + list_tools against an installed strata-memory-mcp binary.

python scripts/mcp_smoke.py /path/to/strata-memory-mcp
"""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def _handshake(command: str) -> None:
    params = StdioServerParameters(command=command, args=[])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listed = await session.list_tools()
            names = [tool.name for tool in listed.tools]
    required = {"recall_context", "forget_memory", "export_memories", "strata_init"}
    missing = required - set(names)
    if missing:
        raise SystemExit(f"missing tools: {sorted(missing)}; got {names}")
    print(f"mcp ok tools={len(names)}")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: mcp_smoke.py /path/to/strata-memory-mcp")
    asyncio.run(_handshake(sys.argv[1]))


if __name__ == "__main__":
    main()
