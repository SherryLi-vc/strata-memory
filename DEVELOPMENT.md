# Development Guide — Strata Memory 2.0

## Setup

```bash
git clone https://github.com/SherryLi-vc/strata-memory.git
cd strata-memory
uv sync --extra dev
uv run pytest -v
uv run strata-memory
```

## Package layout

```
strata_memory/
├── server.py                 # MCP surface (13 tools)
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
│   ├── hygiene.py
│   ├── rebuild.py
│   ├── stats.py
│   └── projection.py
├── embedding/                # SiliconFlow, OpenAI-compatible, local in-process
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

## Releasing

One version lives in `pyproject.toml` and `strata_memory/__init__.py`; `tests/test_version_consistency.py` and `scripts/check_release_version.py` fail when they, the CHANGELOG top entry, the skill metadata, or a release tag disagree.

Publishing uses PyPI Trusted Publishing (OIDC) from `.github/workflows/release.yml`. The repository holds no PyPI token.

One-time setup (maintainer account, not done by CI):

| Field | pypi.org (`/manage/account/publishing/`) | test.pypi.org (`/manage/account/publishing/`) |
|---|---|---|
| PyPI Project Name | `strata-memory-mcp` | `strata-memory-mcp` |
| Owner | `SherryLi-vc` | `SherryLi-vc` |
| Repository name | `strata-memory` | `strata-memory` |
| Workflow name | `release.yml` | `release.yml` |
| Environment name | `pypi` | `testpypi` |

Then in GitHub → Settings → Environments create `testpypi` and `pypi`; give `pypi` required reviewers and limit it to tags `v*`.

Flow:

1. Actions → Release → Run workflow. It builds `<version>.dev<run_number>`, checks metadata, smoke-tests the wheel, and publishes to TestPyPI only. Verify with `uvx --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ strata-memory-mcp==<version>.dev<run_number> --help`.
2. Publish a GitHub release with tag `v<version>` (for example `v2.2.1`). The build job rejects a tag that does not match `pyproject.toml`; the `pypi` job then waits for environment approval and publishes.
