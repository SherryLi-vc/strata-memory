# Strata Memory（分层记忆）MCP

[![PyPI](https://img.shields.io/pypi/v/strata-memory-mcp.svg)](https://pypi.org/project/strata-memory-mcp/)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.org)

**Strata Memory（分层记忆）** 是新一代 AI Agent 记忆中枢系统，专为追求**透明、可控、持久**记忆体验的个人用户与企业场景打造。

它以 **Markdown 文件系统** 为物理底座，将人类记忆的「地层」概念引入 AI 世界，构建出 **L0-L3 四层分层记忆架构**，彻底解决「黑盒不可解释、Token 爆炸、长期遗忘」三大痛点。

---

## ✨ Core Features / 核心特性

- **极致透明** / **Ultimate Transparency**: Markdown + YAML Frontmatter 物理存储，VSCode / Obsidian / Git 直接编辑
- **智能分层** / **L0-L3 Tiered Architecture**: 永驻核心、近期日记、混合检索、冷归档，高效控制 Token
- **混合检索** / **Hybrid Retrieval**: 私有化 BGE-M3 + SQLite/PostgreSQL KG + RRF 融合
- **双模式设计** / **Dual Mode**:
  - **个人模式** / Personal: 集成 CBT（负面图式隔离、48h 冷却期、叙事重构）
  - **企业模式** / Enterprise: Memory Palace 空间化结构、多租户隔离、完整 AuditLog、MES/WMS 状态持久化
- **Agent-Driven Onboarding**: 自动引导配置
- **全私有部署** / Full Private Deployment: 支持内网与 Air-gapped 环境

## 🚀 Quick Start / 快速开始

```bash
# 一键运行
uvx strata-memory-mcp

# 或克隆仓库
git clone https://github.com/vincy/strata-memory.git
cd strata-memory
uv sync
uv run strata-memory-mcp
```

### MCP Client Config / 客户端配置

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "strata-memory": {
      "command": "uv",
      "args": ["run", "strata-memory-mcp"]
    }
  }
}
```

**Hermes** (`~/.hermes/config.yaml`):

```yaml
mcp_servers:
  strata-memory:
    command: uv
    args:
      - run
      - strata-memory-mcp
    timeout: 120
```

**Cursor** — 见 [examples/cursor-mcp.json](examples/cursor-mcp.json)

**Claude Desktop** — 见 [examples/CLAUDE.md](examples/CLAUDE.md)

## 🤖 Agent-Driven Onboarding / 智能引导

首次启动无配置时，宿主 AI 自动读取 `strata://memory/setup-instructions.md`，完成：

1. `get_system_profile()` — 静默硬件探测
2. `search_embedding_recommendations(profile)` — 硬件感知模型匹配
3. 对话式推荐（本地 vs 云端、隐私 vs 性能）
4. `apply_memory_config()` — 一键写配置、初始化 Palace、热重载

零 CLI 命令。零手动 JSON 编辑。Agent 主导，用户只需选择。

## 🔧 Tools / 工具

| Tool | 描述 Description |
|------|-------------|
| `get_system_profile` | 静默硬件探测 Silent hardware detection |
| `search_embedding_recommendations` | 硬件感知模型匹配 Hardware-aware model matching |
| `apply_memory_config` | 应用配置 + 热重载 Config persistence + hot reload |
| `strata_init` | 手动初始化 Manual init with mode selection |
| `memorize` | 写入记忆 Write with psych metadata |
| `wake_up` | 分层唤醒 L0+L1+L2 with CBT defusion |
| `search` | 主动检索 Semantic search with filters |
| `get_health` | 系统状态 Runtime status (30s cache) |

详细示例见 [docs/tools.md](docs/tools.md)

## 🧠 Architecture / 架构

```
L0 (Permanent/永驻)   → Markdown profile     — 核心身份、程序性知识
L1 (Recent/近期)      → Diary entries         — CBT 重构叙事
L2 (Semantic/语义)    → ChromaDB + BGE-M3     — 向量检索 (384-dim)
L3 (Cold/冷归档)      → Markdown archive      — 降级不删除 (Inhibitory Control)
```

- **Embedding**: BGE-M3 via SiliconFlow API (MRL 384-dim) 或本地模型
- **Scoring**: `final_score = base × (1 + log₂(1+usage) × 0.3) × e^salience × decay^days`
- **Decay / 衰减率**: event=0.85, lesson=0.90, preference=0.95, procedure=0.98, core_identity=1.00
- **Storage / 存储**: Markdown + YAML frontmatter + ChromaDB + SQLite
- **Safety / 安全**: CBT 认知扭曲检测、48h 冷却期、负面图式隔离、叙事解离

完整架构见 [docs/architecture.md](docs/architecture.md)

## 🔀 Dual Mode / 双模式

| Feature / 特性 | Personal / 个人 | Company / 企业 |
|---------|----------|---------|
| CBT safety / 认知安全 | ✅ passive | 默认关闭 |
| Emotional tracking / 情感追踪 | ✅ | — |
| AuditLog / 审计日志 | Markdown | Markdown + SQLite |
| Multi-tenancy / 多租户 | — | Wings 隔离 |
| PostgreSQL | — | V2 路线图 |
| Private embedding / 私有部署 | 可选 | 推荐 |

## 📁 Project / 项目结构

```
strata-memory/
├── strata_memory/         # 主包
│   ├── server.py          # MCP Server (8 tools, 5 resources)
│   ├── config.py          # 双模式配置 + 衰减率
│   ├── cli.py             # CLI 入口 (init/health/serve)
│   ├── pipeline/          # memorize / wake / scoring
│   ├── storage/           # markdown / chroma / triples
│   ├── embedding/         # BGE-M3 via SiliconFlow
│   ├── safety/            # CBT 认知安全
│   ├── audit/             # 审计日志
│   └── tools/             # Agent-Driven 工具
├── docs/                  # 架构 + 工具文档
├── examples/              # 客户端配置示例
├── .github/               # CI/CD + Issue/PR 模板
└── tests/                 # 测试
```

详见 [DEVELOPMENT.md](DEVELOPMENT.md)

## 🔒 Security / 安全

所有数据默认本地存储，零外部上传。详见 [SECURITY.md](SECURITY.md)

## 📄 License / 许可证

MIT — 见 [LICENSE](LICENSE)
