# Development Guide

## Environment Setup

```bash
git clone https://github.com/vincy/strata-memory.git
cd strata-memory
uv sync --group dev
```

## Running Locally

```bash
uv run strata-memory-mcp
```

The MCP server starts on stdio — it's designed to be launched by an MCP client
(Claude Desktop, Hermes, Cursor, etc.), not directly by a human.

## Testing

```bash
uv run pytest -v
```

## Architecture

See [docs/architecture.md](docs/architecture.md) for the full architecture document.

### Memory Tiers (L0–L3)

| Tier | Storage | Purpose |
|------|---------|---------|
| **L0** | `l0_profile/*/profile.md` | Permanent decontextualized facts, procedures, core identity |
| **L1** | `l1_diary/*/*.md` | Recent N days of diary entries (CBT-reframed narratives) |
| **L2** | ChromaDB vector store | Semantic search across all indexed memories |
| **L3** | Markdown cold storage | Demoted/expired memories (not deleted — Inhibitory Control) |

### Package Layout

```
strata_memory/
├── server.py              # MCP Server entry point (8 tools, 5 resources)
├── config.py              # Dual-mode config, decay rates, palace management
├── __init__.py            # v0.2.0
├── __main__.py            # CLI entry point
├── audit/
│   └── __init__.py        # AuditLogger — every operation tracked
├── embedding/
│   ├── __init__.py        # Provider registry
│   ├── base.py            # EmbeddingProvider abstract + factory
│   └── bge3_siliconflow.py # BGE-M3 via SiliconFlow API (MRL 384-dim)
├── pipeline/
│   ├── __init__.py
│   ├── memorize.py        # Write pipeline: embed → ChromaDB + Markdown drawer
│   ├── wake.py            # Wake-up: L0 + L1 diary + L2 semantic search
│   └── scoring.py         # Psych-validated scoring: decay × importance × salience
├── safety/
│   └── __init__.py        # CBT cognitive distortion detection + reframing
├── storage/
│   ├── __init__.py
│   ├── markdown.py        # Wing→Room→Drawer filesystem with YAML frontmatter
│   ├── chroma.py          # ChromaDB vector store wrapper
│   └── triples.py         # SQLite semantic network (enhanced psych schema + AuditLog)
├── tools/
│   ├── __init__.py
│   └── system_profile.py  # Agent-Driven onboarding: profile, recommendations, config
└── strata/                # Reserved for Memory Palace extensions
```

### Key Design Decisions

- **White-box memory**: All Markdown files are human-readable and Git-friendly
- **Psych-validated scoring**: `final_score = base × (1 + log₂(1+usage) × 0.3) × e^salience × decay^days`
- **Category-specific decay**: event=0.85, lesson=0.90, preference=0.95, procedure=0.98, core_identity=1.00
- **CBT safety (personal mode)**: 48h cooling-off, negative schema isolation, narrative defusion
- **Dual mode**: Personal (CBT + emotional tracking) vs Company (multi-tenancy + AuditLog)

## MCP Tools

| Tool | Description |
|------|-------------|
| `get_system_profile` | Silent hardware detection (OS, RAM, GPU) |
| `search_embedding_recommendations` | Hardware-aware model matching |
| `apply_memory_config` | Config persistence + hot reload |
| `strata_init` | Manual initialization with mode selection |
| `memorize` | Write memory with psych metadata |
| `wake_up` | L0+L1+L2 session wake-up with CBT defusion |
| `search` | Semantic search with filters |
| `get_health` | Runtime status and stats (30s cache) |

## Enterprise / Company Mode / 企业模式

### Memory Palace Structure / 空间化结构

```
palace/wings/<tenant>/halls/<hall>/rooms/<room>/drawers/<date>.md
```

- **Wings / 业务域**: 对应租户或业务部门（如 `factory_001`, `warehouse_east`）
- **Rooms / 实体**: 具体产线、设备、工位（如 `line-03`, `robot-07`）
- **Drawers / 记录**: 日期分片的 Markdown 文件，含 YAML frontmatter 元数据

### 多租户隔离

- 每个 tenant 独占一个 Wing，通过 `tenant_id` 严格隔离
- AuditLog 按 tenant 分段，支持按操作人/时间/目标过滤
- V2: PostgreSQL RBAC 集成

### 工业场景支持

- **MES 调度状态持久化**: `persist_state()` 记录设备运行状态，TTL 自动过期
- **WMS 知识沉淀**: 库位优化策略、波次拣货规则以 `procedure` 类记忆长期保存
- **全私有部署**: 支持 Air-gapped 环境，零外部依赖（嵌入模型可本地部署）
- **Git 版本控制**: 所有 Markdown 文件天然 Git-friendly，支持变更追溯与回滚

### V2 Enterprise Tools / 规划

| Tool | Purpose |
|------|---------|
| `persist_state` | 设备/调度状态持久化，TTL 过期 |
| `audit_query` | 结构化审计日志查询 |

For Docker deployment, see [docker-compose.yml](docker-compose.yml).
