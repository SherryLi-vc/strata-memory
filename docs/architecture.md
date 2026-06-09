# Strata Memory — Architecture

## Overview

Strata Memory is an L0-L3 tiered hybrid memory system for AI Agents, exposed via the Model Context Protocol (MCP). It models human memory as geological strata with category-specific decay rates and psych-validated scoring.

## Memory Tiers

| Tier | Name | Storage | Purpose | Token Budget |
|------|------|---------|---------|-------------|
| L0 | Core | Markdown profile | Permanent decontextualized facts, procedures | 2000 |
| L1 | Diary | Markdown files | Recent N days of CBT-reframed narratives | 4000 |
| L2 | Semantic | ChromaDB | Vector search with BGE-M3 (384-dim) | 6000 |
| L3 | Cold | Markdown archive | Demoted memories (Inhibitory Control) | — |

## Scoring Formula

```
final_score = base_importance
            × (1 + log₂(1 + usage_count) × 0.3)
            × e^emotional_salience
            × decay_rate^days
```

## Category-Specific Decay Rates

| Category | Rate | Behavior |
|----------|------|----------|
| event | 0.85 | Fades fastest (episodic) |
| lesson | 0.90 | Learned lessons |
| fact | 0.93 | General facts |
| relationship | 0.92 | Social information |
| preference | 0.95 | Tastes, preferences |
| goal | 0.96 | Active goals persist |
| procedure | 0.98 | Procedural knowledge, very stable |
| core_identity | 1.00 | Anchor exemption, no decay |

## Data Flow

```
memorize(content)
  → estimate_emotional_salience() (pipeline/scoring.py)       — keyword screening
  → detect_distortions() (safety/)                             — CBT check
  → write_drawer() (storage/markdown.py)                       — physical Markdown + YAML
  → embed() (embedding/)                                       — BGE-M3 384-dim vector
  → chroma.add() (storage/chroma.py)                           — vector index
  → auditor.log_memorize() (audit/ — called from server.py)    — audit trail

  V2: triples.upsert() (storage/triples.py)                    — semantic network
  V2: compute_score() for automated promotion/demotion

wake_up(query)
  → read_l0_profile() (storage/markdown.py)                    — permanent context
  → read_l1_diary() (storage/markdown.py)                      — recent N days
  → embed(query) (embedding/)                                   — semantic vector
  → chroma.query() (storage/chroma.py)                          — L2 search
  → CBT defusion if negative schema (pipeline/wake.py)         — safety reframing
  → format as flat Markdown                                    — context string
  → auditor.log_wake_up() (audit/ — called from server.py)     — audit trail

search(query)
  → embed(query) (embedding/)                                   — semantic vector
  → chroma.query() + filters (storage/chroma.py)               — filtered search
  → auditor.log_search() (audit/ — called from server.py)      — audit trail
```

## Palace Structure (Filesystem)

```
palace/
├── wings/
│   ├── users/<user_id>/<room>/<date>.md    # Personal mode
│   └── <tenant>/halls/<hall>/rooms/<room>/drawers/<date>.md  # Company mode
├── l0_profile/<wing>/profile.md
├── l1_diary/<wing>/<date>.md
├── l2_vector/                               # ChromaDB
├── l3_cold/
├── audit_logs/<date>.md
├── metadata_db/triples.db                   # SQLite
└── system/
    └── onboarding_complete.md
```

## Dual Mode

### Personal Mode
- CBT cognitive distortion detection (catastrophizing, black-and-white thinking, etc.)
- 48h cooling-off: negative schemas held in L3 before L0 promotion
- Emotional salience scoring
- Narrative reframing (third-person perspective)

### Company Mode / 企业模式
- **Memory Palace 空间化结构**: Wings（业务域）→ Rooms（实体）→ Drawers（记录），对应真实组织结构
- 多租户严格隔离（Wing + tenant_id 命名空间）
- 完整操作审计（AuditLog: Markdown + SQLite），每一次 memorize/wake_up/search 均留痕
- 支持工业场景：MES/WMS 调度状态持久化、产线知识沉淀
- CBT 默认关闭（可手动开启用于教练 Agent）
- 全私有部署 + Git 版本控制（Markdown 天然 Git-friendly）
- PostgreSQL-backed AuditLog + 向量存储（V2 路线图）
- 私有 BGE-M3 部署端点支持

**V2 企业专属工具**（规划中）:

| Tool | 描述 |
|------|------|
| `persist_state` | 设备/产线状态持久化，支持 TTL 过期 |
| `audit_query` | 结构化审计日志查询，按时间/操作人/目标过滤 |

## MCP Protocol Surface

### Tools (8)
| Tool | Side Effects |
|------|-------------|
| get_system_profile | None (read) |
| search_embedding_recommendations | None (read) |
| apply_memory_config | Writes config, inits Palace |
| strata_init | Writes config, inits Palace |
| memorize | Writes drawer + vector + triples + audit |
| wake_up | Reads only (L0+L1+L2) |
| search | Reads only (L2 semantic) |
| get_health | Reads only (30s cache) |

### Resources (5)
- `strata://onboarding/steps.md` — Manual setup guide
- `strata://memory/setup-instructions.md` — Agent-Driven setup guide
- `strata://stats` — System statistics
- `strata://wings` — Wing directory
- `strata://audit/logs` — Audit trail (init-only)

## Security

- Path traversal: `drawer_path()` sanitizes segments + `.resolve()` sandbox
- SQL injection: all queries parameterized; dynamic values type-validated and clamped
- API key: `exclude=True` from serialization; `STRATA_API_KEY` env var
- Multi-tenant isolation: Wings + tenant_id namespace separation
