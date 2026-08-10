# Development Guide — Strata Memory 2.0

## Setup

```bash
git clone https://github.com/vincy/strata-memory.git
cd strata-memory
uv sync --extra dev
uv run pytest -v
uv run strata-memory-mcp
```

## Package layout

```
strata_memory/
├── server.py                 # MCP surface (10 tools)
├── config.py                 # Config + palace paths + truth_db_path
├── governance/
│   ├── quality_kernel.py     # Write-time validation / dedup hash / TTL
│   ├── cbt_middleware.py     # Distortion detect + secret redaction
│   └── errors.py             # LLM-facing how_to_fix errors
├── storage/
│   ├── truth_store.py        # SQLite SoT + FTS5 + audit + trajectory
│   ├── chroma.py             # Rebuildable vector companion
│   ├── markdown.py           # Legacy FS helpers (projection era)
│   └── triples.py            # Legacy KG (optional companion)
├── pipeline/
│   ├── commit.py             # commit_memory + promote_session
│   ├── recall.py             # progressive recall + expand
│   ├── digest.py             # background demote/archive
│   ├── memorize.py           # legacy 0.2 path (unused by server)
│   ├── wake.py               # legacy 0.2 path
│   └── scoring.py            # psych score formula
├── ops/
│   ├── doctor.py
│   ├── rebuild.py
│   ├── stats.py
│   └── projection.py
├── embedding/                # BGE-M3 providers
├── safety/                   # legacy CBT helpers
├── audit/                    # Markdown audit wrapper
└── tools/                    # legacy onboarding helpers
```

## Design checklist for new tools

1. Description must be 作用 + 触发 + 禁忌
2. Prefer intent aggregation over REST 1:1
3. Return structured errors with `how_to_fix`
4. Destructive ops need confirm gate
5. Never dump unbounded text into tool results
6. Log trajectory via TruthStore

## CLI

```bash
python -m strata_memory.cli init
python -m strata_memory.cli doctor
python -m strata_memory.cli stats
python -m strata_memory.cli digest          # dry-run
python -m strata_memory.cli digest --apply
python -m strata_memory.cli project
python -m strata_memory.cli migrate         # dry-run 0.2 → 2.0
python -m strata_memory.cli migrate --apply
python -m strata_memory.cli serve
# console script alias:
strata-memory-migrate --apply --report /tmp/mig.json
```

## Tests

```bash
uv run pytest -v
```

Core coverage: Quality Kernel, Truth Store, commit/recall/expand, ops.
