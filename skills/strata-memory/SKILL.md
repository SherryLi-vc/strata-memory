---
name: strata-memory
description: Installs and operates strata-memory, an open-source MCP memory server that stores vetted facts in local SQLite and recalls them as short cards before expanding full text. Use when the user asks for persistent agent memory, long-term context across sessions, shared memory for multiple agents, or help connecting an MCP memory server in Claude Code, Cursor, Claude Desktop, or Hermes.
summary: Free integration skill for strata-memory, an open-source MCP memory hub. Your agent installs and connects the server, stores vetted facts in a local SQLite source of truth, and recalls them with a search-then-expand flow instead of flooding the context window.
version: 1.0.0
tags: [mcp, memory, agent-memory, persistent-memory, long-term-memory, multi-agent, sqlite, vector-search, rag, claude-code, cursor, claude-desktop, hermes, open-source]
keywords: [mcp memory server, persistent context, agent memory, shared memory, progressive recall, hybrid search, chromadb, bge-m3]
use_cases:
  - Give a coding agent memory of user preferences and project decisions across sessions
  - Share durable facts between several agents through one MCP server
  - Promote session scratch notes into durable memory only after confirmation
  - Recall relevant memories as short cards, then expand only the ones that matter
docs_url: https://github.com/SherryLi-vc/strata-memory
license: MIT
compatibility: Requires an MCP host (Claude Code, Cursor, Claude Desktop, or Hermes), Python 3.11+, and uv. Embeddings default to an offline local provider with no API key. Set STRATA_EMBEDDING_PROVIDER to siliconflow or openai_compatible to use a remote endpoint. Memories stay under STRATA_PALACE. The configured embedding endpoint receives memory text and recall queries unless the provider is local.
metadata:
  author: Vincy Zhang
  open_source: https://github.com/SherryLi-vc/strata-memory
  server_version: "2.2.1"
  free: "true"
---

# Strata Memory

## Purpose

strata-memory is an open-source MCP memory server (v2.2.1, MIT) for one agent or several agents sharing a palace.

- SQLite is the single source of truth (memories, audit, trajectories).
- Chroma is a companion vector index. Rebuild it from SQLite; do not treat it as authoritative.
- Markdown from `strata_project` is a read-only human view.
- Writes go through a Quality Kernel and CBT middleware.
- Recall is two-step: `recall_context` returns short cards (`id`, `summary`, `score`). `expand_memory_detail` loads full text for one id.

Repository: https://github.com/SherryLi-vc/strata-memory

This skill does not bundle the server. The distribution name is `strata-memory-mcp`. Do not run `uvx strata-memory`; that name on PyPI is a different package. Install from git: `uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp`. PyPI install (`uvx strata-memory-mcp`) is coming soon. Semantic weights: `uvx --from 'strata-memory-mcp[local] @ git+https://github.com/SherryLi-vc/strata-memory' strata-memory-mcp`.

## When to Use

- The user wants persistent memory, long-term context, or an MCP memory server
- Several agents should share durable facts through one palace
- Session scratch notes should become durable only after the user confirms them
- Recall should stay small: search cards first, then expand the hits that matter

## When not to use

- Storing passwords, API keys, tokens, or other secrets
- Recording relative times (`yesterday`, `刚才`, `today`) inside `fact_claim`; use an ISO date
- Storing hedged wording (`probably`, `maybe`, `也许`) as `memory_type: factual_truth`
- Rebuilding the vector index unless the user has agreed (`confirm=true`)

## Data and network

Tell the user this before the first write or recall:

- Rows live under `STRATA_PALACE` (default `~/.strata/palace`).
- The configured embedding endpoint receives memory text and recall queries (`commit_memory`, `promote_session`, `recall_context`, and index rebuild), unless the provider is `local`.
- Default is `local`: no API key, text stays on the machine. Without the `local` extra the server uses a hashing embedder. `uvx --from 'strata-memory-mcp[local] @ git+https://github.com/SherryLi-vc/strata-memory' strata-memory-mcp` (or `uv sync --extra local` in a clone) uses `sentence-transformers/all-MiniLM-L6-v2`. The first run downloads weights and needs a network. Offline, set `STRATA_LOCAL_EMBED_BACKEND=hash` instead of waiting on that download. A changed embedder must be rebuilt; the index refuses mixed vectors.
- Optional cloud: provider `siliconflow`, model `BAAI/bge-m3`, base URL `https://api.siliconflow.cn/v1`. That model returns 1024 dimensions and is truncated to `STRATA_EMBEDDING_DIMENSION` (default 384). A saved `config.json` that already names `siliconflow` keeps that provider.
- `STRATA_EMBEDDING_PROVIDER=openai` or `openai_compatible` calls any OpenAI-compatible `POST /embeddings` endpoint. Set `STRATA_EMBEDDING_BASE_URL` and `STRATA_EMBEDDING_MODEL`. The vector length must equal `STRATA_EMBEDDING_DIMENSION` (OpenAI `text-embedding-3-small` uses 1536 when that provider is selected). Then rebuild the index.
- `STRATA_EMBEDDING_PROVIDER=local` runs an in-process model (default `sentence-transformers/all-MiniLM-L6-v2`, 384 dimensions). Install with `uv sync --extra local`. Text stays on the machine.
- A local server (Ollama, llama.cpp, TEI, vLLM) is `openai_compatible` with a loopback `STRATA_EMBEDDING_BASE_URL` such as `http://127.0.0.1:11434/v1`. Loopback does not require an API key. Text is sent to that URL.
- Key lookup for HTTP providers: explicit argument, `STRATA_EMBEDDING_API_KEY`, `STRATA_API_KEY`, then `SILICONFLOW_API_KEY` (SiliconFlow) or `OPENAI_API_KEY` (OpenAI-compatible). Empty values, values shorter than 20 characters, and values containing `...` are rejected.
- Never ask the user to paste a key into chat. Never echo a key, write one into memory, or commit one. The user sets it in their own shell profile or host config.

## Install this skill

The skill folder name is `strata-memory` and matches `name` above. In this repository the folder is `skills/strata-memory/`. Hosts that scan the checkout:

| Host | In this repository | Every project on the machine |
|------|--------------------|------------------------------|
| Claude Code | `.claude/skills/strata-memory` | `~/.claude/skills/strata-memory` |
| Cursor | `.claude/skills/strata-memory` (Cursor also reads this) | `~/.cursor/skills/strata-memory` |
| Hermes | `.hermes/skills/strata-memory` after `hermes skills trust` in the repo | `~/.hermes/skills/strata-memory` |
| Claude Desktop | Does not scan the git checkout | Upload a zip of this folder (top entry `strata-memory/SKILL.md`) from the app's Skills settings, or enable it on the signed-in claude.ai account |

Copy the directory. Do not rename it. Claude Desktop still needs the MCP entry below; the skill is the procedure, the server is the memory.

To pack this folder for Agensi, zip `skills/strata-memory` so the archive root contains `strata-memory/SKILL.md`.

## Setup

1. Confirm Python 3.11+ and `uv`. If one is missing, point the user at that tool's install page and stop. `git` is only needed to develop the server.
2. The default embedding provider is `local` and needs no API key. Ask the user to set `STRATA_API_KEY` or `STRATA_EMBEDDING_API_KEY` themselves only when they choose a cloud endpoint (shell profile, `~/.strata/env`, Claude Desktop's local config, or `~/.hermes/.env`). Do not request the value and do not repeat it. A loopback `STRATA_EMBEDDING_BASE_URL` also skips the key.
3. Start the server (no API key) from git:

```bash
export STRATA_PALACE="${STRATA_PALACE:-$HOME/.strata/palace}"
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp
```

PyPI install (`uvx strata-memory-mcp`) is coming soon. Do not use the PyPI name `strata-memory`.

Or print a host snippet and merge it yourself:

```bash
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp setup --host cursor
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp setup --host claude-code
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp setup --host claude-desktop
```

`strata-memory-mcp` is the same server, for configs that already call that command.

4. Register the server with the matching file in `references/`. The templates run `uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp` and do not set `STRATA_EMBEDDING_PROVIDER`, so a saved palace provider stays in effect. Add a key field only if the user switches to a cloud embedder. Claude Desktop's file is JSON with no comments.
5. Call `strata_init` once (`mode` `personal`, or `company` with `tenant_id`). Then call `strata_doctor`. Continue only if `summary.api_key.usable` is true. The same flag is on the check named `embedding_api_key`. The payload never includes the key.
6. Each session: `recall_context` first, `expand_memory_detail` only for useful ids, `commit_memory` for vetted facts, `promote_session` when scratch notes were confirmed.

## Host configuration

Merge the template into the host file. Do not replace the rest of an existing config.

### Claude Code

Template: `references/claude-code.mcp.json`.

- Project scope: `.mcp.json` at the project root. Claude Code expands `${STRATA_API_KEY}` from the environment when the session starts. Approve the server in `/mcp` the first time.
- User scope: merge the same `mcpServers.strata-memory` object into `~/.claude.json`. Do not overwrite the rest of that file.

Do not run `claude mcp add --env STRATA_API_KEY=<key>`. That copies the secret into the command line, shell history, and the chat. If the user prefers the CLI, they run it in their own terminal with the variable already exported, and the agent does not substitute the value:

```bash
claude mcp add --scope user --transport stdio strata-memory \
  --env STRATA_API_KEY="${STRATA_API_KEY}" \
  --env "STRATA_PALACE=${STRATA_PALACE:-$HOME/.strata/palace}" \
  -- uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp
```

### Cursor

Template: `references/cursor-mcp.json`.

- All projects: `~/.cursor/mcp.json`
- One project: `.cursor/mcp.json`

`type` is `stdio`. `${env:STRATA_API_KEY}` and `${userHome}` are Cursor interpolations. A Cursor window started from a desktop launcher often does not see shell exports. In that case, the user creates `~/.strata/env` locally (`STRATA_API_KEY=` plus the full key, mode `0600`) and sets `"envFile": "${userHome}/.strata/env"` on this server, removing the `${env:STRATA_API_KEY}` line. Do not create that file from chat and do not commit it.

Reload MCP from Cursor's Customize page after saving.

### Claude Desktop

Template: `references/claude-desktop.json`.

Open the file from Settings → Developer → Edit Config, then restart the app. Known locations:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

On Linux, use the file Edit Config opens. Desktop does not expand `${VAR}` and does not inherit a terminal's environment. The user replaces the empty `STRATA_API_KEY` locally. If `uv` is not on the app's `PATH`, set `command` to the absolute `uv` binary (often `~/.local/bin/uv`).

### Hermes

Template: `references/hermes-config.yaml`. Merge under `mcp_servers` in `~/.hermes/config.yaml` (`HERMES_HOME` overrides `~/.hermes`).

1. The user writes the full key and the clone path into `~/.hermes/.env` (not a redacted `sk-xxx...yyy` value):

```bash
STRATA_API_KEY=<full key set by the user, not by the agent>
STRATA_DIR=/absolute/path/to/strata-memory
```

2. Install the launcher from the clone:

```bash
mkdir -p ~/.hermes/scripts
cp examples/strata-wrapper.sh ~/.hermes/scripts/strata-wrapper.sh
chmod +x ~/.hermes/scripts/strata-wrapper.sh
```

3. Point `mcp_servers.strata-memory.command` at that script with an absolute path. The script reads `STRATA_API_KEY`, `STRATA_DIR`, and optional `STRATA_PALACE` from the environment and from `~/.hermes/.env`. It no longer defaults `STRATA_DIR` to a personal folder.
4. Reload with `/reload-mcp` or restart the session.

The wrapper's later fallbacks are `SILICONFLOW_API_KEY`, a one-line key in `~/.strata/api_key`, and a non-redacted `sk-` value in `~/.openclaw/openclaw.json`. Prefer `STRATA_API_KEY` in `~/.hermes/.env`.

## Tools (13)

| Tool | Use for |
|------|---------|
| `strata_init` | Create the palace, SQLite store, and config. Once per deployment. |
| `commit_memory` | Write one vetted fact. Requires `user_id`, `memory_type`, `fact_claim`, `confidence_score`. |
| `promote_session` | Move that session's scratch rows to durable memory. Requires `user_id` and `session_id`. |
| `recall_context` | Ranks every tier, including L0, by relevance to `query`. Honours `limit`. `include_l0` (default true) drops L0 when false. Returns cards, not full text. Requires `user_id` and `query`. |
| `expand_memory_detail` | Full text for one id from a card. Scope-checked. Requires `user_id` and `memory_id`. |
| `forget_memory` | Delete by `memory_id`, or by filter (`memory_type`, `layer`, `session_id`, `query`, or `match_all`) with `confirm=true`. Stays inside `user_id` / `tenant_id`. Removes the SQLite row and the vector id so a rebuild cannot restore it. |
| `export_memories` | JSON export for one `user_id` and tenant. CLI: `strata-memory export --user USER --out memories.json`. |
| `strata_doctor` | SQLite vs index consistency, plus whether the embedding key is usable. No arguments. |
| `strata_rebuild_index` | Wipe and rebuild vectors from SQLite. Requires `confirm=true`. Does not delete SQLite. |
| `strata_stats` | L0–L3 token watermarks. Optional `user_id`. |
| `strata_project` | Write the read-only Markdown projection. Optional `user_id`. |
| `strata_digest` | Demote or archive by TTL and score. Default `dry_run=true`. |
| `strata_hygiene` | Expired rows, hash duplicates, secret-residue scan. Default `dry_run=true`. Optional FTS rebuild. |

`memory_type` is one of `factual_truth`, `user_preference`, `procedure_rule`, `episodic_event`, `decision_record`.

`context_depth` on recall is `shallow` or `deep` (default `deep`). `current_turn_only=true` prefers the current session.

Errors look like `{"status":"error","error_code":"...","message":"...","how_to_fix":"...","retry_safe":true}`. Follow `how_to_fix`.

## Write example

`commit_memory`:

```json
{
  "user_id": "user_001",
  "memory_type": "user_preference",
  "fact_claim": "User prefers dark mode in VS Code with Monokai Pro theme.",
  "confidence_score": 0.92,
  "session_id": "sess_2026-08-04"
}
```

## Recall example

`recall_context`:

```json
{
  "user_id": "user_001",
  "query": "IDE theme preferences",
  "context_depth": "deep",
  "limit": 8
}
```

Then `expand_memory_detail` for one id only:

```json
{
  "user_id": "user_001",
  "memory_id": "<id from hits>"
}
```

Do not paste the card list back into the prompt as if it were the full memory.

## Quality Kernel

Hard rejects:

- Credentials (`SECRET_DETECTED`): passwords, API keys, tokens, `sk-...`, private keys
- Emotion with no fact (`EMOTION_ONLY`)
- Fuzzy time in any claim (`FUZZY_TIME`), including 刚才 / 昨天 / 今天 / yesterday / today / last week / recently
- Speculative wording only when `memory_type` is `factual_truth` (`SPECULATION_AS_TRUTH`)

`confidence_score` must be between 0.1 and 1.0. Below the configured floor the row stays scratch.

## Safety rules

- `expand_memory_detail` fails with `SCOPE_VIOLATION` when `user_id` or `tenant_id` does not match. Do not retry with another user's id.
- `strata_rebuild_index` without `confirm=true` returns `CONFIRMATION_REQUIRED`. Ask the user first.
- `strata_hygiene` and `strata_digest` stay on `dry_run=true` until the user wants the archive applied.
- Do not copy `secret_hits` text into public logs or chat.
- If `strata_doctor` reports a bad key, stop and tell the user to fix the environment. Do not ask them to send the key.

## Validation

- `python3 --version` is 3.11 or newer, and `uv` and `git` run.
- The clone URL is `https://github.com/SherryLi-vc/strata-memory`.
- No command in the transcript contains the raw API key.
- `strata_doctor` reports the SQLite store and `summary.api_key.usable` true, and does not print the key.
- A recall result is a card list. Full text was loaded only through `expand_memory_detail` for a returned id.
- A committed `fact_claim` has no secret pattern and no fuzzy time word.

## Further reading

- Architecture: https://github.com/SherryLi-vc/strata-memory/blob/main/docs/architecture.md
- Tool contracts: https://github.com/SherryLi-vc/strata-memory/blob/main/docs/tools.md
- Security: https://github.com/SherryLi-vc/strata-memory/blob/main/SECURITY.md
- Changelog: https://github.com/SherryLi-vc/strata-memory/blob/main/CHANGELOG.md
- Brand marks: https://github.com/SherryLi-vc/strata-memory/blob/main/assets/brand/README.md — Agensi listing icon is `assets/brand/extensions/icon_light_transparent_512.png` (recall dot, 512). Use `icon_dark_transparent_512.png` on a dark tile.
