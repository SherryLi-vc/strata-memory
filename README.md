# Strata Memory MCP

[![Version](https://img.shields.io/badge/version-0.2.0-blue)](https://pypi.org/project/strata-memory-mcp/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.org)

**Strata Memory** is a transparent, L0-L3 tiered, Markdown-backed hybrid memory system for AI Agents via MCP.

It models human memory as geological strata — core identity persists at L0, recent context at L1, semantic search at L2, and cold storage at L3. All memories are plain Markdown files with YAML frontmatter, making them VSCode-editable, Git-diffable, and fully auditable.

## Why Strata Memory

| Problem | Solution |
|---------|----------|
| Black-box vector DBs | White-box Markdown filesystem |
| Token explosion | L0-L3 tiered retrieval with hard caps |
| Long-term forgetting | Psych-validated decay scoring + Inhibitory Control |
| Negative self-talk loops | CBT cognitive distortion detection + 48h cooling-off |
| No enterprise audit trail | AuditLog (Markdown + SQLite), multi-tenant Wings |

## Quick Start

```bash
# Clone and run
git clone https://github.com/vincy/strata-memory.git
cd strata-memory
uv sync
uv run strata-memory-mcp
```

### MCP Client Configuration

**Claude Desktop** (`claude_desktop_config.json`):

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

**Hermes** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  strata-memory:
    command: uv
    args:
      - run
      - strata-memory-mcp
    timeout: 120
```

**Cursor** — see [examples/cursor-mcp.json](examples/cursor-mcp.json).

**Claude Desktop** — see [examples/CLAUDE.md](examples/CLAUDE.md).

**Hermes** — see [examples/hermes-config.yaml](examples/hermes-config.yaml).

## Agent-Driven Onboarding

Strata Memory features silent, conversation-driven setup. When first launched without config, the Host AI reads `strata://memory/setup-instructions.md` and:

1. Calls `get_system_profile()` — silent hardware detection
2. Calls `search_embedding_recommendations(profile)` — hardware-aware model matching
3. Presents the user with ranked options (local vs cloud, privacy vs performance)
4. Calls `apply_memory_config(chosen)` — writes config, inits Palace, hot reloads

No CLI commands. No manual JSON editing. The Agent leads; the user just answers.

## Tools

| Tool | Description |
|------|-------------|
| `get_system_profile` | Silent hardware detection (OS, RAM, GPU accelerator) |
| `search_embedding_recommendations` | Hardware-aware model matching from MTEB-informed table |
| `apply_memory_config` | Apply config, init Palace, hot reload |
| `strata_init` | Manual initialization with mode selection |
| `memorize` | Write memory with psych metadata (emotional_salience, category, tags) |
| `wake_up` | L0+L1+L2 session wake-up with CBT defusion for negative schemas |
| `search` | Active semantic search with category/time/tag filters |
| `get_health` | Runtime status: mode, vector/drawer counts, config summary (30s cache) |

## Architecture

```
L0 (Permanent)   → Markdown profile files     — core identity, procedures
L1 (Recent)      → Diary entries (N days)     — CBT-reframed narratives
L2 (Semantic)    → ChromaDB + BGE-M3 (384d)   — vector search
L3 (Cold)        → Markdown cold storage       — demoted, not deleted
```

- **Embedding**: BGE-M3 via SiliconFlow API (MRL-truncated 384-dim) or local model
- **Scoring**: `final_score = base_importance × (1 + log₂(1+usage) × 0.3) × e^salience × decay^days`
- **Decay rates**: event=0.85, lesson=0.90, preference=0.95, procedure=0.98, core_identity=1.00
- **Storage**: Markdown + YAML frontmatter + ChromaDB + SQLite triples
- **Safety**: CBT distortion detection, 48h cooling-off, negative schema isolation, defusion

## Dual Mode

| Feature | Personal | Company |
|---------|----------|---------|
| CBT safety | ✅ passive | Off by default |
| Emotional tracking | ✅ | — |
| AuditLog | Markdown only | Markdown + SQLite |
| Multi-tenancy | — | Wings per tenant |
| PostgreSQL | — | V2 roadmap |
| Private embedding | Optional | Recommended |

## Project Layout

See [DEVELOPMENT.md](DEVELOPMENT.md) for full architecture and development guide.

## Security

All data is stored locally by default. See [SECURITY.md](SECURITY.md) for our security policy and recent audit fixes.

## License

MIT — see [LICENSE](LICENSE).
