# Changelog

## [2.2.1] — 2026-10-28

- Hybrid recall fusion weights are configurable, with a deterministic held-out R@1/R@3 evaluation harness.

### Docs and install
- README, README.zh-CN, SKILL.md, the `setup --host` snippets and the shipped JSON templates install from git (`uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp`). `uvx strata-memory-mcp` is marked coming soon until the first PyPI release.
- Tool count is 13 everywhere (README, README.zh-CN, SKILL.md, DEVELOPMENT.md); a test checks the docs against the tools the server registers.

### Vector index
- `strata_rebuild_index` embeds eligible rows and writes vectors in batches of up to 128, with per-row fallback for a failed batch.
- `strata_rebuild_index(tenant_id=...)` deletes and re-adds only that tenant's vectors. It used to reset the whole collection and re-add one tenant, dropping every other tenant's vectors while returning ok. An unstamped or mismatched index escalates a tenant-scoped call to a full rebuild (`scope: "all"`).
- `strata_doctor` reports `status: "degraded"` whenever it lists an issue, warnings included, so `healthy: false` never comes with `status: "ok"`. A new `severity` field (`none`, `warn`, `error`) keeps the distinction.
- `strata_doctor` checks vector coverage by id (`vector_coverage`, `INDEX_INCOMPLETE`). After a failed or interrupted rebuild it reports `degraded` instead of healthy.
- `recall_context` on an index without an embedder stamp (built before 2.2.1) falls back to lexical recall with `fusion.vector_skipped` and a warning instead of failing with `EMBEDDER_UNSTAMPED`. Run `strata_rebuild_index(confirm=true)` once after upgrading. See "Upgrading from an older version" in the README.

### Privacy and isolation
- Secrets in `commit_memory` are masked by default: a detected secret is replaced with `[redacted:<kind>]` before the row is hashed, stored, embedded or audited, and the response lists `secrets_redacted`. `on_secret: "reject"` in `config.json` (or `STRATA_ON_SECRET=reject`) restores the old refusal with `SECRET_DETECTED`. The rules (`governance/secrets.py`) cover AWS, GitHub, GitLab, Slack, Stripe, Google and `sk-` keys, npm/PyPI tokens, JWTs, private key blocks, passwords, bearer tokens and credentials in URLs. Hygiene previews and migration reports no longer echo a raw secret.
- `recall_context` marks cut summaries with ` …[truncated]` and `summary_truncated`, and reports `truncated` plus `truncation` (scan limit reached, cards dropped by the token budget, summaries cut).
- `recall_context` treats an empty `tenant_id` as the default tenant, not a wildcard. Lexical, FTS and vector candidates are all checked against the SQLite row's `tenant_id` and `user_id`; the vector query always filters on `tenant_id`. Previously an empty tenant could return another tenant's rows for the same `user_id`.
- The `recall_context` audit row stores `q_len`, hit and token counts, not the query text. Older rows written as `q=<text> ...` are rewritten to `q=[redacted] ...` when the store opens, with `secure_delete` and a WAL checkpoint so the text leaves the database files.

### Packaging
- One version, 2.2.1, everywhere: `pyproject.toml`, `__version__`, the MCP handshake `server_version`, `strata_init`, the CLI, new configs, and the skill metadata. A test keeps them in sync.
- `.github/workflows/release.yml` publishes with PyPI Trusted Publishing (OIDC, no stored token): a manual run publishes a `.devN` build to TestPyPI (environment `testpypi`); a published GitHub release whose tag matches the version publishes to PyPI (environment `pypi`). `testpypi.yml` is folded into it.
- Distribution name stays `strata-memory-mcp`. `strata-memory` on PyPI is a different project.
- `mcp` is pinned to `>=1.0.0,<2`. mcp 2.x removed `Server.list_tools`.
- CI installs the wheel into a clean venv with no lockfile and smoke-tests `--help`, `setup`, and an MCP handshake.

### Embeddings
- Host snippets do not set `STRATA_EMBEDDING_PROVIDER`.
- The vector index stores provider, model, dimension, and backend. A mismatch refuses vector use until rebuild.
- A saved config that only sets `provider` uses that provider's model and URL. A palace file with no embedding block stays on SiliconFlow. A missing config file still defaults to local.
- `strata_init` and `strata_doctor` report the effective provider, model, and backend.
- A semantic local model that cannot download fails with a short message. `STRATA_LOCAL_EMBED_BACKEND=hash` opts into hashing. `STRATA_EMBEDDING_HASH_FALLBACK=1` falls back after a failed download.

### Forget and export
- `forget_memory` deletes the supersede chain by default (`include_chain=false` keeps a single row).
- Audit rows for forgotten ids stay, with fact text replaced by `[redacted]`.
- Forget and export return `total`, `remaining`, and `next_offset`.

## [2.2.0] — 2026-10-28

### Recall
- L0 (`factual_truth`, `user_preference`, `procedure_rule`) is ranked by query relevance. Scores are no longer hardcoded to 1.0.
- `limit` applies to the merged list (L0, scratch, and other layers).
- `include_l0` is exposed on `recall_context` (default true). `current_turn_only` still skips L0.
- Only returned cards are touched, so a recall no longer rewrites `last_accessed` on every L0 row.

### Forget and export
- `forget_memory`: delete by id, or by filter with `confirm=true`. Scoped to `user_id` and `tenant_id`. Deletes the SQLite row (FTS trigger included) and the Chroma id, so `strata_rebuild_index` cannot restore it.
- `export_memories` and `strata-memory export` write a JSON document for one user/tenant.

### Install
- Distribution name is `strata-memory-mcp`. `uvx strata-memory` is a different PyPI project.
- Default embedding provider is `local` (no API key). Without the `local` extra, embeddings are an offline hashing fallback. `config.json` values already saved for another provider are left alone.
- `strata-memory setup --host cursor|claude-code|claude-desktop` prints a snippet.

### Breaking
- Fresh installs no longer default to SiliconFlow. Set `STRATA_EMBEDDING_PROVIDER=siliconflow` to keep that endpoint.
- Callers that depended on every L0 card being prepended, ignoring `limit`, will now receive at most `limit` cards.

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
