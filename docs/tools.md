# Strata Memory — Tool Reference

All 8 MCP tools with real input/output examples. Tools are called by the Host AI Agent; the MCP server runs on stdio transport.

---

## 1. `get_system_profile` — Silent Hardware Detection

No parameters. Called first during Agent-Driven onboarding.

**Input:**
```json
{}
```

**Output:**
```json
{
  "os": "Darwin",
  "arch": "arm64",
  "ram_gb": 16.0,
  "cpu_cores": 8,
  "accelerator": "mps",
  "hostname": "hostname.redacted"
}
```

---

## 2. `search_embedding_recommendations` — Hardware-Aware Model Matching

Takes an optional `profile` (from `get_system_profile`). Returns ranked recommendations.

**Input:**
```json
{
  "profile": {
    "os": "Darwin",
    "arch": "arm64",
    "ram_gb": 16.0,
    "cpu_cores": 8,
    "accelerator": "mps"
  }
}
```

**Output:**
```json
{
  "profile": { "os": "Darwin", "ram_gb": 16.0, "accelerator": "mps", "..." : "..." },
  "recommendations": [
    {
      "provider": "siliconflow",
      "model": "BAAI/bge-m3",
      "dimension": 384,
      "tier": "cloud",
      "reason": "Recommended: 16GB shared memory is tight. Cloud API keeps it light."
    },
    {
      "provider": "local",
      "model": "all-MiniLM-L6-v2",
      "dimension": 384,
      "tier": "local",
      "reason": "Ultra-light local fallback. Runs comfortably on 16GB shared memory."
    }
  ],
  "note": "Recommendations are sorted by priority (best first). Present the top 2-3 to the user."
}
```

---

## 3. `apply_memory_config` — Apply Config + Hot Reload

The final step of Agent-Driven onboarding. Writes config, inits Palace, creates welcome drawer. Hot reload — no MCP restart needed.

**Input:**
```json
{
  "mode": "personal",
  "provider": "siliconflow",
  "model": "BAAI/bge-m3",
  "api_key": "sk-...",
  "base_url": "https://api.siliconflow.cn/v1",
  "dimension": 384,
  "cbt_mode": "passive"
}
```

**Output:**
```json
{
  "status": "ok",
  "message": "Memory Palace initialized in personal mode with siliconflow/BAAI/bge-m3.",
  "palace_path": "/Users/.../.strata/palace",
  "mode": "personal",
  "provider": "siliconflow",
  "model": "BAAI/bge-m3",
  "dimension": 384,
  "cbt_mode": "passive",
  "tenant_id": "",
  "init_results": {
    "wings_dir": "/Users/.../.strata/palace/wings",
    "vector_dir": "/Users/.../.strata/palace/l2_vector",
    "welcome_drawer": "/Users/.../.strata/palace/wings/system/onboarding_complete.md"
  },
  "next": "Use `memorize` to start recording memories. Use `wake_up` at session start."
}
```

**Company mode:**
```json
{
  "mode": "company",
  "provider": "siliconflow",
  "model": "BAAI/bge-m3",
  "api_key": "sk-...",
  "cbt_mode": "off",
  "tenant_id": "factory_001"
}
```

---

## 4. `strata_init` — Manual Initialization

Legacy manual path. Prefer `apply_memory_config` for Agent-Driven flow. API key can also come from `STRATA_API_KEY` env var.

**Input (Personal):**
```json
{
  "api_key": "sk-...",
  "mode": "personal",
  "provider": "siliconflow",
  "model": "BAAI/bge-m3",
  "cbt_mode": "passive"
}
```

**Input (Company):**
```json
{
  "api_key": "sk-c947...",
  "mode": "company",
  "provider": "siliconflow",
  "model": "BAAI/bge-m3",
  "cbt_mode": "off",
  "tenant_id": "factory_001"
}
```

**Output:**
```
Strata Memory initialized (personal mode).

Palace: /Users/.../.strata/palace
Embedding: siliconflow/BAAI/bge-m3
CBT: passive (cooling=48h)
Audit: markdown-only
Tenant: N/A (personal mode)

Next: Use `memorize` to start recording memories.
```

---

## 5. `memorize` — Write Memory

Records content with psych-validated metadata. Writes Markdown drawer + ChromaDB vector index. CBT detection runs automatically in personal mode.

**Input:**
```json
{
  "user_id": "user_001",
  "content": "User prefers dark mode for coding. Uses VS Code with Monokai Pro theme.",
  "category": "preference",
  "importance": 0.8,
  "room": "general",
  "context_tags": ["coding", "ide", "theme"]
}
```

**Output:**
```json
{
  "status": "ok",
  "drawer": "/Users/.../.strata/palace/wings/users/user_001/general/2026-06-09.md",
  "doc_id": "users/user_001/general/2026-06-09",
  "wing": "users/user_001",
  "room": "general",
  "date": "2026-06-09",
  "category": "preference",
  "emotional_salience": 0.0,
  "is_negative_schema": false,
  "context_tags": ["coding", "ide", "theme"],
  "characters": 65,
  "tokens_approx": 21
}
```

**With negative content (CBT active):**
```json
{
  "user_id": "user_001",
  "content": "I completely messed up the presentation. I'm always terrible at everything.",
  "category": "event",
  "importance": 0.7
}
```

*The system detects catastrophizing + overgeneralization distortions and marks `is_negative_schema: true`. In passive CBT mode, this memory will get defusion framing on recall.*

---

## 6. `wake_up` — Session Wake-Up

L0 profile + L1 diary + optional L2 semantic search. CBT defusion applied to negative schemas.

**Shallow (L0+L1 only, fast):**
```json
{
  "user_id": "user_001",
  "query": "coding preferences",
  "context_depth": "shallow"
}
```

**Deep (L0+L1+L2, full context):**
```json
{
  "user_id": "user_001",
  "query": "coding preferences and IDE setup",
  "context_depth": "deep",
  "limit": 5
}
```

**Output (flat Markdown string with stats footer):**
```markdown
## Core Profile (L0 — Permanent)
User is a senior backend engineer. Prefers Python and Go. Values clean architecture.

## Recent Context (L1 Diary)
### 2026-06-09
Discussed new project structure. User prefers flat layouts over deeply nested folders.
### 2026-06-08
Debugged memory leak in production. Root cause: unclosed HTTP connections.

## Related Memories (L2 Semantic)
### Memory 1 (relevance: 0.92)
- Date: 2026-06-05
- Category: preference
- Room: general

User prefers dark mode for coding. Uses VS Code with Monokai Pro theme.

<!-- strata-wake-stats: v=0.2.0 mode=personal tokens=420 l0=1 l1=2 l2=3 neg=0 cbt=passive depth=deep -->
```

---

## 7. `search` — Active Semantic Search

Full-text semantic search across L2 with category/time/tag filters. Results capped at 1500 chars each.

**Basic search:**
```json
{
  "query": "coding preferences",
  "user_id": "user_001",
  "limit": 10
}
```

**Filtered search:**
```json
{
  "query": "meeting notes",
  "user_id": "user_001",
  "limit": 5,
  "category": "event",
  "from_date": "2026-06-01",
  "to_date": "2026-06-09",
  "context_tags": ["work", "meeting"]
}
```

**Output:**
```markdown
# Search Results: "meeting notes"
*State-dependent boost: work, meeting*

## Result 1 (relevance: 0.89)
- **Date**: 2026-06-05
- **Category**: event
- **Room**: work

Discussed Q3 roadmap. Priority items: auth refactor, memory system integration, dashboard.

---

## Result 2 (relevance: 0.76)
- **Date**: 2026-06-03
- **Category**: event
- **Room**: work

Sprint planning. Assigned tickets for MCP integration. Deadline: June 15.

---
```

---

## 8. `get_health` — Runtime Status

Returns full system status. Cached for 30 seconds.

**Input:**
```json
{}
```

**Output:**
```json
{
  "version": "0.2.0",
  "initialized": true,
  "mode": "personal",
  "palace": "/Users/.../.strata/palace",
  "tenant": "N/A",
  "embedding": {
    "provider": "siliconflow",
    "model": "BAAI/bge-m3",
    "dimension": 384,
    "mode": "cloud"
  },
  "cbt": {
    "enabled": true,
    "mode": "passive",
    "cooling_hours": 48
  },
  "audit": {
    "enabled": false,
    "log_to_markdown": true
  },
  "memory": {
    "vector_count": 42,
    "drawer_count": 15,
    "l0_token_budget": 2000,
    "l1_days": 3,
    "l2_top_k": 10,
    "promotion_threshold": 0.8,
    "demotion_threshold": 0.3,
    "cooling_hours": 48
  },
  "scoring": {
    "promotion_min_usage": 5,
    "l3_demotion_days": 30
  }
}
```

---

## Tool Quick Reference

| Tool | Required Params | Optional Params | Side Effects |
|------|----------------|-----------------|-------------|
| `get_system_profile` | — | — | None |
| `search_embedding_recommendations` | — | `profile` | None |
| `apply_memory_config` | `mode`, `provider`, `model` | `api_key`, `base_url`, `dimension`, `cbt_mode`, `tenant_id` | Writes config, inits Palace, hot reload |
| `strata_init` | `api_key` | `mode`, `provider`, `model`, `base_url`, `cbt_mode`, `tenant_id` | Writes config, inits Palace |
| `memorize` | `user_id`, `content` | `category`, `importance`, `room`, `context_tags` | Writes drawer + vector |
| `wake_up` | `user_id`, `query` | `context_depth`, `limit` | Reads only |
| `search` | `query`, `user_id` | `limit`, `category`, `from_date`, `to_date`, `context_tags` | Reads only |
| `get_health` | — | — | Reads only (30s cache) |
