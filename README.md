# strata-memory

<p align="center">
  <a href="./assets/brand/README.md">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/extensions/lockup_dark_transparent.svg">
      <img alt="strata-memory" src="./assets/brand/extensions/lockup_light_transparent.svg" width="420">
    </picture>
  </a>
</p>

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.org)

**It remembers why you decided.**

When a fact changes, strata does not overwrite the row. The previous memory is archived and linked (`supersedes_id` / `superseded_by`). A `decision_record` keeps the choice, the date, and what it replaced, so a later session can explain why the current fact is the current fact.

```json
{
  "user_id": "user_001",
  "memory_type": "decision_record",
  "fact_claim": "On 2026-08-10 the team decided SQLite is the memory source of truth, replacing the Markdown drawers.",
  "confidence_score": 0.95
}
```

Recall returns a short card. `expand_memory_detail` loads the chain: the new claim, `supersedes_id`, and the archived predecessor.

---

## Quickstart

Python 3.11+ and [uv](https://docs.astral.sh/uv/). No API key. Text stays on the machine.

```bash
uvx strata-memory-mcp
```

The PyPI project name is `strata-memory-mcp`. `strata-memory` on PyPI is a different package. Do not install that name.

Until this package is published, start it from git:

```bash
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp
```

That starts the MCP server on stdio. Data lives in `STRATA_PALACE` (default `~/.strata/palace`). A new palace defaults to the local embedder. A `config.json` that already names a provider is left alone. Host snippets do not set `STRATA_EMBEDDING_PROVIDER`, because an environment value overrides the saved palace.

Print a snippet for your host and merge it into the existing config. Do not replace the rest of the file.

```bash
uvx strata-memory-mcp setup --host cursor
uvx strata-memory-mcp setup --host claude-code
uvx strata-memory-mcp setup --host claude-desktop
```

| Host | Config |
|------|--------|
| Cursor | `~/.cursor/mcp.json` or `.cursor/mcp.json` |
| Claude Code | `.mcp.json` or `mcpServers` in `~/.claude.json` |
| Claude Desktop | Settings → Developer → Edit Config |
| Hermes | `~/.hermes/config.yaml` — see [skills/strata-memory/references/hermes-config.yaml](skills/strata-memory/references/hermes-config.yaml) |

Cursor example (`uvx strata-memory-mcp setup --host cursor`):

```json
{
  "mcpServers": {
    "strata-memory": {
      "type": "stdio",
      "command": "uvx",
      "args": ["strata-memory-mcp"],
      "env": {
        "STRATA_PALACE": "${userHome}/.strata/palace"
      }
    }
  }
}
```

Claude Desktop's snippet is the same shape and is valid JSON. Desktop does not expand `${VAR}`; edit the palace path in that file if you need to. Before the package is on PyPI, the `args` array can be `["--from", "git+https://github.com/SherryLi-vc/strata-memory", "strata-memory-mcp"]`.

Then call `strata_init` once and `strata_doctor`. Both report the effective embedding provider, model, and backend. With the default provider, `summary.api_key.usable` is true because no key is required.

## Examples

Commit a preference:

```json
{
  "user_id": "user_001",
  "memory_type": "user_preference",
  "fact_claim": "User prefers the Monokai Pro theme with dark mode in VS Code.",
  "confidence_score": 0.92
}
```

Recall cards. `limit` applies to L0, scratch, and every other tier. `include_l0` defaults to true.

```json
{
  "user_id": "user_001",
  "query": "Monokai Pro theme dark mode",
  "limit": 3,
  "include_l0": true
}
```

Expand one id:

```json
{ "user_id": "user_001", "memory_id": "<id from hits>" }
```

Forget one memory, or a filtered set. A filter does nothing until `confirm` is true. The row is removed from SQLite and from the vector index, so `strata_rebuild_index` cannot bring it back.

```json
{ "user_id": "user_001", "memory_id": "<id>" }
```

```json
{ "user_id": "user_001", "memory_type": "episodic_event", "confirm": true }
```

Export JSON (MCP `export_memories`, or the CLI):

```bash
uvx strata-memory-mcp export --user user_001 --out memories.json
```

## What the default embedder is

`local` tries fastembed, then sentence-transformers. If neither is installed, it uses a deterministic hashing embedder: offline, no download, no key. Hashing matches shared words. It does not match paraphrases. `scripts/recall_benchmark.py` reports literal-overlap and paraphrase scores separately, and it runs the semantic backend only when fastembed is installed.

For a semantic model:

```bash
uvx --from 'strata-memory-mcp[local]' strata-memory-mcp
```

That pulls the optional `local` extra (fastembed / ONNX). The first run downloads `sentence-transformers/all-MiniLM-L6-v2` and needs a network. Offline, that download fails quickly and tells you to set `STRATA_LOCAL_EMBED_BACKEND=hash` (or `STRATA_EMBEDDING_HASH_FALLBACK=1`) instead of hanging. After a successful download the weights stay on the machine. The index stores the embedder identity. A provider or model change refuses vector reads and writes until `strata_rebuild_index(confirm=true)`.

Cloud endpoints are opt-in. They receive memory text and recall queries.

| Variable | Role |
|----------|------|
| `STRATA_EMBEDDING_PROVIDER` | `local` (default), `siliconflow`, `openai`, `openai_compatible` |
| `STRATA_EMBEDDING_BASE_URL` | OpenAI-compatible `POST /embeddings` root. SiliconFlow is `https://api.siliconflow.cn/v1` |
| `STRATA_EMBEDDING_MODEL` | Model id |
| `STRATA_EMBEDDING_DIMENSION` | Vector length. Default 384 |
| `STRATA_EMBEDDING_API_KEY` or `STRATA_API_KEY` | Required for non-loopback HTTP providers |

A `config.json` that already names `siliconflow` keeps that provider. Set `STRATA_EMBEDDING_PROVIDER=local` to switch, then rebuild.

## Tools

| Tool | Use |
|------|-----|
| `strata_init` | Create the palace and SQLite store |
| `commit_memory` | Write one vetted fact |
| `promote_session` | Promote that session's scratch rows |
| `recall_context` | Ranked cards. `limit` covers every tier. `include_l0` controls L0 |
| `expand_memory_detail` | Full text for one id |
| `forget_memory` | Delete by id, or by filter with `confirm=true` |
| `export_memories` | JSON for one user and tenant |
| `strata_doctor` | SQLite vs index, and whether a key is required |
| `strata_rebuild_index` | Rebuild vectors from SQLite. `confirm=true` |
| `strata_stats` | Layer counts |
| `strata_project` | Read-only Markdown view |
| `strata_digest` | Demote or archive. Default dry-run |
| `strata_hygiene` | Expired rows, hash duplicates, secret scan |

`memory_type` is `factual_truth`, `user_preference`, `procedure_rule`, `episodic_event`, or `decision_record`. The first three default to L0.

## FAQ

**Where do memories live?**  
SQLite under `STRATA_PALACE` (default `~/.strata/palace`). Chroma is a rebuildable index. Markdown from `strata_project` is a read-only view.

**Does this phone home?**  
Not with the default `local` provider. A cloud provider or a non-loopback `STRATA_EMBEDDING_BASE_URL` receives memory text and queries.

**Why is a fact different from last month?**  
Look at `decision_record` rows and at `supersedes_id` / `superseded_by` on the expanded card. The old row is archived, not destroyed, unless you `forget_memory`.

**Can I delete something?**  
Yes. `forget_memory` by id, or by `memory_type` / `layer` / `session_id` / `query` with `confirm=true`. Deletion is scoped to `user_id` and `tenant_id`. A rebuild will not restore deleted rows.

**How do I back up?**  
`export_memories` or `strata-memory export --user USER --out memories.json`. `strata_project` is the Markdown view of the same store.

**Does recall dump the whole palace?**  
No. You pass a query and a `limit` (1–20). L0 facts, preferences, and procedures are ranked against that query. They are not pinned to the front of the list with a score of 1.

**Will it store a password or an API key?**  
The quality kernel rejects credentials, emotion-only text, fuzzy times (`yesterday`, `刚才`), and speculation stored as `factual_truth`. Other memory tools also block or redact secrets. This is a write-time check, not a claim that the feature is unique.

**The doctor says the key is missing.**  
You selected a cloud provider. Set the key in the host environment, not in chat. Or switch `STRATA_EMBEDDING_PROVIDER` back to `local`.

## Breaking changes in 2.2

- New installs default to `STRATA_EMBEDDING_PROVIDER=local`. A saved `config.json` that names `siliconflow` (or another provider) is unchanged. A palace file with no embedding block stays on SiliconFlow, which was the historical default.
- `recall_context` ranks L0 and scratch with everything else and applies `limit` to that list. Scores are no longer a constant 1.0. `include_l0` is on the MCP tool (default true). `current_turn_only` still leaves L0 out.
- The distribution name is `strata-memory-mcp`. `uvx strata-memory` installs a different project.

## Known issues

These are present on main and are not fixed here:

- With an empty `tenant_id`, vector recall can return another tenant's rows for the same `user_id`, because that query filters only on `user_id`.
- `strata_rebuild_index` inside the server process can fail with a readonly Chroma database and leave the vector layer unusable. Rebuild from a fresh process if that happens.

## Develop

```bash
git clone https://github.com/SherryLi-vc/strata-memory.git
cd strata-memory
uv sync --extra dev
uv run pytest -v
uv run python scripts/recall_benchmark.py
```

Packaging check: `uv build` and `uvx twine check dist/*`. Publishing is a maintainer action. This repo does not contain a PyPI token.

Architecture: [docs/architecture.md](docs/architecture.md) · Tools: [docs/tools.md](docs/tools.md) · Security: [SECURITY.md](SECURITY.md) · 中文: [README.zh-CN.md](README.zh-CN.md)

## License

MIT — see [LICENSE](LICENSE)
