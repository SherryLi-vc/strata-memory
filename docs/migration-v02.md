# Migrate 0.2 Markdown → 2.0 SQLite

Strata Memory 0.2 stored drawers as Markdown + YAML. 2.0 uses **SQLite as Single Source of Truth**. This guide imports legacy drawers without deleting the originals.

## What gets scanned

| Path | Treatment |
|------|-----------|
| `wings/users/<uid>/<room>/<date>.md` | personal drawers |
| `wings/<tenant>/halls/.../drawers/<date>.md` | company drawers |
| `l0_profile/**/profile.md` | → `factual_truth` / L0 |
| `l1_diary/**/<date>.md` | → `episodic_event` |
| `l3_cold/**` | imported if Markdown present |

Skipped: `index.md`, `audit_logs/`, `projection/`.

## Category mapping

| 0.2 `category` | 2.0 `memory_type` |
|----------------|-------------------|
| preference | user_preference |
| procedure | procedure_rule |
| fact / core_identity | factual_truth |
| event / lesson | episodic_event |
| goal | user_preference |
| relationship | factual_truth |

## Safety rules

1. **Secrets** (`password`, `sk-…`, tokens) → **skipped** by default  
2. **Relative time** (`昨天` / `today`) → grounded with drawer date, e.g. `[2026-06-08] …`  
3. **Negative schema** flags preserved; blocked from L0  
4. **Idempotent**: same `content_hash` → `deduped` (usage_count++), no duplicate rows  
5. Source Markdown is **never deleted**

## Quick start

```bash
cd /path/to/strata-memory

# 1) Preview (no writes)
export STRATA_PALACE=~/.strata/palace   # or your 0.2 palace path
uv run python -m strata_memory.cli migrate --palace "$STRATA_PALACE"

# 2) Apply import into SQLite
uv run python -m strata_memory.cli migrate --palace "$STRATA_PALACE" --apply \
  --report /tmp/strata-migrate-report.json

# 3) Rebuild vector companion from SoT (needs API key)
export STRATA_API_KEY=sk-...
uv run python -m strata_memory.cli migrate --palace "$STRATA_PALACE" --apply --rebuild-vectors

# Or use the console script
uv run strata-memory-migrate --palace "$STRATA_PALACE" --apply
```

## CLI flags

| Flag | Meaning |
|------|---------|
| `--palace PATH` | 0.2 palace root (default `STRATA_PALACE` or `~/.strata/palace`) |
| `--apply` | Write to SQLite (omit = dry-run) |
| `--user-id ID` | Only this user |
| `--tenant-id ID` | Force tenant on all rows |
| `--import-secrets` | Try redact+import instead of skip (not recommended) |
| `--strict-fuzzy` | Do not auto-ground relative time |
| `--rebuild-vectors` | After apply, full Chroma rebuild from SoT |
| `--report PATH` | Write JSON summary |
| `--min-confidence 0.7` | Confidence stamped on migrated rows |

## Recommended sequence

```text
1. Backup palace/  (cp -a or tar)
2. uv run strata-memory-mcp  → strata_init if no config.json yet
3. migrate --apply
4. strata_doctor (or CLI doctor)
5. migrate --apply --rebuild-vectors   # optional, for semantic search
6. strata_project                       # optional Markdown projection from SoT
```

## Programmatic API

```python
from pathlib import Path
from strata_memory.ops import migrate_palace

report = migrate_palace(
    Path.home() / ".strata" / "palace",
    dry_run=False,
    user_id_filter="alice",
)
print(report.summary())
```

## Verify

```bash
uv run python -m strata_memory.cli stats
uv run python -m strata_memory.cli doctor
```

Expect `truth_store.active > 0` and (after rebuild) non-empty vector count.
