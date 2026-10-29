# Strata Memory 2.0 — Architecture

## Design laws

1. **LLM decides; deterministic code executes.**
2. **SQLite is the only Source of Truth.**
3. **Vector DB and Markdown are companions / projections — rebuildable.**
4. **Tool descriptions are legal contracts** (作用 / 触发 / 禁忌).
5. **Progressive disclosure** — never dump full corpus into context.

## Storage stack

```
palace/
├── config.json                 # mode, budgets, embedding (no full api_key)
├── truth/
│   └── strata.db               # SoT: memories, audit_log, trajectory, FTS5
├── l2_vector/                  # SQLite vector companion (rebuildable)
├── projection/                 # read-only Markdown dump
├── audit_logs/                 # optional human Markdown audit
└── system/
```

### memories table (core fields)

| Field | Role |
|-------|------|
| id | Opaque memory id |
| tenant_id, user_id, session_id | 3-axis isolation |
| memory_type | factual_truth / user_preference / procedure_rule / episodic_event |
| fact_claim / summary / detail | claim + progressive fields |
| content_hash | dedup |
| layer | L0 / L1 / L2 / L3 / scratch |
| confidence, importance, emotional_salience | scoring inputs |
| ttl_seconds, expires_at | lifecycle |
| is_negative_schema, is_scratch | safety / buffer flags |

## Write path

```
commit_memory
  → QualityKernel.validate (type, length, secrets, fuzzy time, speculation)
  → CBTMiddleware.assess (distortions + redaction)
  → TruthStore.find_by_hash (dedup → touch)
  → TruthStore.insert_memory (TTL/layer deterministic)
  → embed + SQLite vector upsert (best-effort; failure does not roll back SoT)
  → audit + trajectory
```

## Read path

```
recall_context
  → candidates: L0 (unless include_l0=false) + this session's scratch + other layers
  → lexical BM25 over that pool, optionally blended with vector similarity
  → multi-signal score, then limit, then token budget
  → return [{id, summary, score, layer, type}]  ONLY

expand_memory_detail(id)
  → scope check (user_id + tenant_id)
  → full detail (cap 4000 chars) + CBT defusion if needed
```

## Hybrid RRF

```
score(d) = Σ 1 / (k + rank_i(d) + 1)   for each ranked list i
k = 60 (standard)
```

FTS5 `OR` queries still propose candidates. The score that orders cards is Okapi BM25 over the candidate pool (lexical), blended with vector similarity when an embedding is available, then the multi-signal factors (recency, importance, freshness). A missing vector branch leaves lexical ranking in place.

## CBT & cooling

- Pure Python regex middleware (not LLM conscience)
- Negative schema → force scratch + block L0
- Passive recall: defusion frame; active: hide negatives

## Lifecycle (digest job)

- TTL expired → `archive` (Inhibitory Control — no hard delete)
- Low score / long unaccessed → demote L3 or archive
- Run via `strata_digest` (prefer dry_run first) or cron

## Ops

| Tool | Purpose |
|------|---------|
| strata_doctor | SoT vs index health |
| strata_rebuild_index | wipe vectors, re-embed from SQLite |
| strata_stats | waterlines + trajectory |
| strata_project | Markdown views |

## Dual mode

| | personal | company |
|--|----------|---------|
| CBT | on (passive) | off by default |
| tenant_id | optional | required at init |
| audit | SQLite always | SQLite + emphasis |

## Security red lines

- No plaintext API keys in config.json
- No cross-principal expand
- Destructive index rebuild requires `confirm=true`
- Secrets never enter SoT (Quality Kernel + redaction)
