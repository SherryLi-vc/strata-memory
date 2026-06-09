# Strata Memory MCP — Claude Desktop Integration

Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "strata-memory": {
      "command": "uv",
      "args": ["run", "strata-memory-mcp"]
    }
  }
}
```

Or with full Python path:

```json
{
  "mcpServers": {
    "strata-memory": {
      "command": "python3",
      "args": ["-m", "strata_memory"]
    }
  }
}
```

Restart Claude Desktop after making changes.
