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
  "limit": 8
}
```

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
      "score": 1.0
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

## Quick matrix

| Tool | Required | Side effects |
|------|----------|--------------|
| strata_init | — | Writes config + DB |
| commit_memory | user_id, memory_type, fact_claim, confidence_score | SoT + optional vector |
| promote_session | user_id, session_id | SoT + vector |
| recall_context | user_id, query | Read + usage_count++ |
| expand_memory_detail | user_id, memory_id | Read + usage_count++ |
| strata_doctor | — | Read |
| strata_rebuild_index | confirm=true | Wipes vectors only |
| strata_stats | — | Read |
| strata_project | — | Writes projection/ |
| strata_digest | — | May archive/demote |
