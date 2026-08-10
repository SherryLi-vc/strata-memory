# Changelog

## [2.1.0] — 2026-08-10

### Memory 3.0 Slice C (engineering maturity)
- **decision_record** type + forced typed TTL/status/validator_kind defaults
- **Near-dup supersede** version chain (`supersedes_id` / `superseded_by`)
- **Provenance** JSON + authority/sensitivity/entity columns (schema v3)
- **Multi-signal rerank** on RRF with `score_breakdown` + `filtered` reasons
- **current_turn_only** session filter on `recall_context`
- **strata_hygiene** tool: expired archive, hash dups, secret scan, FTS rebuild
- **strata_doctor** reports hash duplicates and secret residuals

## [2.0.1] — 2026-08-09

### Fixed (Hermes / SiliconFlow key chain)
- **No more silent embed skip**: `_get_state()` used to leave `_embed_provider=None` when `api_key` empty; now raises `EMBEDDING_API_KEY_MISSING` with `how_to_fix`
- **Reject redacted keys**: `sk-xxx...yyy` (OpenClaw UI placeholders) fail `is_usable_api_key()`
- **Key resolve order**: `STRATA_API_KEY` → `SILICONFLOW_API_KEY` → `OPENAI_API_KEY`
- **strata_doctor** reports `embedding_api_key` usable/length/reason (never full key)
- **SiliconFlow 401/403** return actionable auth errors
- **Hermes wrapper** (`examples/strata-wrapper.sh`): prefer `~/.hermes/.env` / `~/.strata/api_key`; pick longest non-redacted `sk-` from openclaw.json (not the truncated `memorySearch.remote.apiKey` path)

## [2.0.0] — 2026-08-04

Industrial-grade rewrite per *Strata-Memory 2.0 白皮书*. Breaking change vs 0.2.x tool names.

### Architecture
- **SQLite as Single Source of Truth** (`palace/truth/strata.db`)
- **ChromaDB demoted** to rebuildable companion index
- **Markdown demoted** to read-only projection (`strata_project`)
- Principal isolation: `tenant_id` + `user_id` + `session_id`
- Scratch buffer vs durable layers; `promote_session` gate

### Write path (Quality Kernel)
- New tool: `commit_memory` (replaces `memorize`)
- Deterministic metadata: content hash, TTL, layer, dedup
- Hard reject: secrets, fuzzy time, emotion-only, speculation-as-truth
- CBT middleware: distortion detect + redaction + 48h cooling sandbox
- LLM-facing errors with `how_to_fix` guidance

### Read path (Progressive disclosure)
- `recall_context` — Hybrid RRF (vector + FTS5), returns `{id, summary, score}` only
- `expand_memory_detail` — scoped second-stage full text
- Token waterline budgets enforced on recall

### Ops
- `strata_doctor` — SoT ↔ index consistency
- `strata_rebuild_index` — wipe+rebuild vectors from SQLite (`confirm=true` gate)
- `strata_stats` — L0–L3 token waterlines + trajectory
- `strata_project` — Markdown projection dump
- `strata_digest` — background demote/archive (TTL + score)

### Removed / reduced (Phase-1 减法)
- Removed as first-class tools: `get_system_profile`, `search_embedding_recommendations`, `apply_memory_config`, `memorize`, `wake_up`, `search`, `get_health`
- Onboarding consolidated into `strata_init` + resources

### Migration from 0.2.x
1. Install 2.0, run `strata_init` (new palace or existing `STRATA_PALACE`)
2. Map calls: `memorize` → `commit_memory`; `wake_up`/`search` → `recall_context` + `expand_memory_detail`
3. **Bulk import old Markdown drawers:**
   ```bash
   uv run python -m strata_memory.cli migrate --palace ~/.strata/palace          # dry-run
   uv run python -m strata_memory.cli migrate --palace ~/.strata/palace --apply  # write SQLite
   uv run strata-memory-migrate --apply --rebuild-vectors                       # + vector rebuild
   ```
   See [docs/migration-v02.md](docs/migration-v02.md).
4. Or re-ingest critical facts via `commit_memory`
5. `strata_rebuild_index(confirm=true)` after embedding config is set

## [0.2.0] — 2026-06-09

### Added
- Agent-Driven Onboarding tools
- `get_health` 30s cache
- Structured parameter validation

### Fixed
- SQL LIMIT clamping, API key env fallback, path traversal sandbox
- L2 document char caps

## [0.1.0] — 2026-06-08

### Added
- Initial MCP release: L0–L3, BGE-M3, Markdown + Chroma + CBT
