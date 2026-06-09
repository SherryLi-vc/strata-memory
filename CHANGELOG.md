# Changelog

## [0.2.0] — 2026-06-09

### Added
- Agent-Driven Onboarding: `get_system_profile`, `search_embedding_recommendations`, `apply_memory_config` tools
- `strata://memory/setup-instructions.md` resource for Agent-guided setup
- `get_health` 30-second TTL cache
- Structured parameter validation with clear error messages

### Changed
- Upgraded MCP initialization to `InitializationOptions` with `ServerCapabilities`

### Fixed
- **P0-01**: SQL injection via `LIMIT` string interpolation — `int()` clamping (triples.py)
- **P0-02**: API key plaintext storage — `exclude=True` + `STRATA_API_KEY` env var fallback (config.py)
- **P0-03**: Path traversal via user/room params — segment sanitization + `.resolve()` sandbox (markdown.py)
- **P1-01**: wake_up L2 documents now capped at 1500 chars with truncation notice
- **P1-02**: search results now capped at 1500 chars with truncation notice
- **P1-03**: Structured parameter validation returns missing params with expected schema

## [0.1.0] — 2026-06-08

### Added
- Initial release: MCP Server with 5 tools (strata_init, memorize, wake_up, search, get_health)
- L0-L3 tiered memory architecture
- BGE-M3 embedding via SiliconFlow API (MRL 384-dim)
- Markdown filesystem storage with YAML frontmatter
- ChromaDB vector storage
- SQLite triples semantic network
- CBT cognitive distortion detection and narrative defusion
- Dual-mode: personal (CBT + emotional tracking) and company (multi-tenant + AuditLog)
- Psych-validated scoring with category-specific decay rates
