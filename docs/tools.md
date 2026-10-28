# Strata Memory 2.0 — Tool Reference

All tool descriptions follow **作用 + 触发 + 禁忌**. Errors return:

```json
{
  "status": "error",
  "error_code": "FUZZY_TIME",
  "message": "...",
  "how_to_fix": "Replace relative time with ISO date...",
  "retry_safe": true
}
```

---

## strata_init

Initialize palace, SQLite SoT, config.

```json
{ "mode": "personal", "api_key": "optional-if-STRATA_API_KEY-set" }
```

Embedding provider, model, base URL, and dimension come from the environment when the tool arguments are omitted:

- `STRATA_EMBEDDING_PROVIDER` — `local` (default, no API key), `siliconflow`, `openai`, or `openai_compatible`
- `STRATA_EMBEDDING_BASE_URL` — OpenAI-compatible embeddings root. SiliconFlow default `https://api.siliconflow.cn/v1`
- `STRATA_EMBEDDING_MODEL` — SiliconFlow default `BAAI/bge-m3`; local default `sentence-transformers/all-MiniLM-L6-v2`
- `STRATA_EMBEDDING_DIMENSION` — default `384` (bge-m3 is truncated to this). OpenAI `text-embedding-3-small` defaults to `1536` when that provider is selected
- `STRATA_EMBEDDING_API_KEY` or `STRATA_API_KEY` — required for non-loopback HTTP providers

`local` runs in-process (`uv sync --extra local`) and does not send text to an embedding API. Every other provider sends memory text and recall queries to the configured endpoint. A loopback `STRATA_EMBEDDING_BASE_URL` does not require a key.

Company:

```json
{ "mode": "company", "tenant_id": "factory_001" }
```

---

## commit_memory

```json
{
  "user_id": "user_001",
  "memory_type": "user_preference",
  "fact_claim": "User prefers dark mode in VS Code with Monokai Pro theme.",
  "confidence_score": 0.92,
  "session_id": "sess_1",
  "is_scratch": false,
  "context_tags": ["ide", "theme"]
}
```

Success:

```json
{
  "status": "ok",
  "memory_id": "a1b2c3d4e5f60718",
  "layer": "L0",
  "deduplicated": false,
  "indexed": true
}
```

Common errors: `SECRET_DETECTED`, `FUZZY_TIME`, `SPECULATION_AS_TRUTH`, `CLAIM_TOO_SHORT`, `LOW_CONFIDENCE` (→ scratch).

---

## promote_session

```json
{ "user_id": "user_001", "session_id": "sess_1" }
```

---

## recall_context

```json
{
  "user_id": "user_001",
  "query": "coding IDE preferences",
  "context_depth": "deep",
  "limit": 8,
  "include_l0": true
}
```

`limit` caps the merged list. L0 is ranked with the other tiers. `include_l0: false` omits L0.

Response shape:

```json
{
  "status": "ok",
  "hits": [
    {
      "id": "a1b2c3d4e5f60718",
      "summary": "User prefers dark mode...",
      "memory_type": "user_preference",
      "layer": "L0",
      "score": 0.62
    }
  ],
  "token_estimate": 120,
  "note": "Call expand_memory_detail for full text."
}
```

---

## expand_memory_detail

```json
{ "user_id": "user_001", "memory_id": "a1b2c3d4e5f60718" }
```

`SCOPE_VIOLATION` if user_id / tenant mismatch.

---

## strata_doctor

No params. Returns checks + issues + recommendation.

---

## strata_rebuild_index

```json
{ "confirm": true }
```

Without `confirm=true` → `CONFIRMATION_REQUIRED`.

---

## strata_stats

Optional `{ "user_id": "user_001" }`. Returns waterlines, alerts, trajectory.

---

## strata_project

Optional `{ "user_id": "user_001" }`. Writes `palace/projection/**`.

---

## strata_digest

```json
{ "dry_run": true }
```

Set `dry_run: false` to apply demotions/archives.

---

## strata_hygiene

```json
{
  "dry_run": true,
  "archive_expired": true,
  "rebuild_fts": false
}
```

Default `dry_run=true`. Set `dry_run=false` to archive expired rows. Do not paste `secret_hits` text into public logs. Optional `user_id` limits the scan.

---

## Quick matrix

| Tool | Required | Side effects |
|------|----------|--------------|
| strata_init | — | Writes config + DB |
| commit_memory | user_id, memory_type, fact_claim, confidence_score | SoT + optional vector |
| promote_session | user_id, session_id | SoT + vector |
| recall_context | user_id, query | Read + usage_count++ |
| expand_memory_detail | user_id, memory_id | Read + usage_count++ |
| forget_memory | user_id, and id or filter | Deletes SQLite + vector ids. Filter needs confirm=true |
| export_memories | user_id | Read JSON |
| strata_doctor | — | Read |
| strata_rebuild_index | confirm=true | Wipes vectors only |
| strata_stats | — | Read |
| strata_project | — | Writes projection/ |
| strata_digest | — | May archive/demote |
| strata_hygiene | — | May archive expired rows; may rebuild FTS |
