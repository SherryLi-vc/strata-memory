# strata-memory

<p align="center">
  <a href="./assets/brand/README.md">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="./assets/brand/extensions/lockup_dark_transparent.svg">
      <img alt="strata-memory" src="./assets/brand/extensions/lockup_light_transparent.svg" width="420">
    </picture>
  </a>
</p>

[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-Compatible-blue)](https://modelcontextprotocol.org)

**它记得你为什么做出这个决定。**

事实变化时，旧行不会被覆盖。旧记忆归档，并用 `supersedes_id` / `superseded_by` 串成版本链。`decision_record` 留下决定、日期，以及它取代了什么。之后的会话可以解释「为什么现在这条才算数」。

英文文档是 [README.md](README.md)。下面是同一版本的中文说明。

## 快速开始

需要 Python 3.11+ 和 [uv](https://docs.astral.sh/uv/)。默认不需要 API key，正文留在本机。

```bash
uvx strata-memory-mcp
```

PyPI 上的项目名是 `strata-memory-mcp`。`strata-memory` 是别人的包，不要安装那个名字。还没发布到 PyPI 时：

```bash
uvx --from git+https://github.com/SherryLi-vc/strata-memory strata-memory-mcp
```

数据目录是 `STRATA_PALACE`（默认 `~/.strata/palace`）。新 palace 默认 `local`。已经写了提供方的 `config.json` 保持原样。配置片段不会设置 `STRATA_EMBEDDING_PROVIDER`。

给宿主打印一段配置，合并进现有文件，不要整文件覆盖：

```bash
uvx strata-memory-mcp setup --host cursor
uvx strata-memory-mcp setup --host claude-code
uvx strata-memory-mcp setup --host claude-desktop
```

然后调用一次 `strata_init`，再调用 `strata_doctor`。默认提供方下 `summary.api_key.usable` 为 true，因为不需要密钥。

`strata-memory-mcp` 是同一个服务器，已有配置可以继续用这个命令。

## 例子

写入一条偏好：

```json
{
  "user_id": "user_001",
  "memory_type": "user_preference",
  "fact_claim": "User prefers the Monokai Pro theme with dark mode in VS Code.",
  "confidence_score": 0.92
}
```

召回。`limit` 对 L0、scratch 和其他层一起生效。`include_l0` 默认 true。

```json
{
  "user_id": "user_001",
  "query": "Monokai Pro theme dark mode",
  "limit": 3,
  "include_l0": true
}
```

忘掉一条，或按过滤条件删除。过滤删除必须 `confirm=true`。SQLite 行和向量 id 都会去掉，之后 `strata_rebuild_index` 不会把它们找回来。

```json
{ "user_id": "user_001", "memory_id": "<id>" }
```

导出 JSON：

```bash
uvx strata-memory-mcp export --user user_001 --out memories.json
```

## 默认嵌入

`local` 会先尝试 fastembed，再尝试 sentence-transformers。两个都没装时，使用确定性的哈希嵌入：离线、不下载、不需要 key。哈希匹配的是相同的词，不是改写后的句子。

语义模型：

```bash
uvx --from 'strata-memory-mcp[local]' strata-memory-mcp
```

这会安装可选的 `local` extra。第一次可能下载 `sentence-transformers/all-MiniLM-L6-v2`，之后留在本机。换提供方、模型或维度后要重建索引。

云端端点是可选项。一旦选用，记忆正文和召回查询会发到那个端点。SiliconFlow 的地址是 `https://api.siliconflow.cn/v1`，模型 `BAAI/bge-m3`。已经写了 `siliconflow` 的 `config.json` 不会被改掉。

## 工具

| 工具 | 用途 |
|------|------|
| `strata_init` | 创建 palace 和 SQLite |
| `commit_memory` | 写入一条经过校验的事实 |
| `promote_session` | 把该会话的 scratch 晋升为持久记忆 |
| `recall_context` | 按相关度排序的卡片。`limit` 覆盖所有层 |
| `expand_memory_detail` | 按 id 展开全文 |
| `forget_memory` | 按 id 删除，或带 `confirm=true` 按过滤条件删除 |
| `export_memories` | 导出当前用户和租户的 JSON |
| `strata_doctor` | SQLite 与索引是否一致，以及是否需要 key |
| `strata_rebuild_index` | 从 SQLite 重建向量。必须 `confirm=true` |
| `strata_stats` | 分层计数 |
| `strata_project` | 只读 Markdown |
| `strata_digest` | 降级或归档。默认 dry-run |
| `strata_hygiene` | 过期、重复、秘密残留扫描 |

`memory_type`：`factual_truth`、`user_preference`、`procedure_rule`、`episodic_event`、`decision_record`。前三类默认进 L0。

## 常见问题

**记忆存在哪？**  
`STRATA_PALACE` 下的 SQLite。Chroma 是可以重建的索引。`strata_project` 的 Markdown 只是只读视图。

**会把正文发出去吗？**  
默认 `local` 不会。云端提供方或非回环的 `STRATA_EMBEDDING_BASE_URL` 会收到正文和查询。

**为什么这条事实和上个月不一样？**  
看 `decision_record`，以及展开后的 `supersedes_id` / `superseded_by`。旧行是归档，不是删除，除非调用了 `forget_memory`。

**能删除吗？**  
可以。按 id，或按 `memory_type` / `layer` / `session_id` / `query` 且 `confirm=true`。范围限定在 `user_id` 和 `tenant_id`。重建索引不会恢复已删除的行。

**召回会把整个库倒出来吗？**  
不会。必须带 query 和 `limit`（1–20）。L0 的事实、偏好、规程按查询排序，不再固定排在最前面、分数也不再恒为 1。

**会存密码或 API key 吗？**  
Quality Kernel 会拒绝凭据、纯情绪、模糊时间（`yesterday`、`刚才`），以及写成 `factual_truth` 的推测。别的记忆工具也会拒绝或脱敏。这是写入时检查，不是独有能力。

## 2.2 的行为变化

- 新安装默认 `STRATA_EMBEDDING_PROVIDER=local`。`config.json` 里已经写了 `siliconflow` 或其他提供方的，保持原样。
- `recall_context` 把 L0 和 scratch 放进同一排序，`limit` 作用在这张名单上。`include_l0` 出现在 MCP 参数里（默认 true）。`current_turn_only` 仍然不注入 L0。
- 发行包名是 `strata-memory-mcp`。`uvx strata-memory` 装到的是另一个项目。

## 从旧版本升级

2.2.1 之前建的向量索引没有嵌入器标记（`l2_vector/embedder.json`）。升级后：

1. `recall_context` 照常可用，但只走词法召回。返回里有 `fusion.vector_skipped = "EMBEDDER_UNSTAMPED"` 和一条提示。`commit_memory` 照常写 SQLite，在索引打上标记之前不写向量。
2. 执行一次 `strata_rebuild_index`（`confirm=true`）。它从 SQLite 重新嵌入全部有效记忆并写入标记。用云端提供方时会把每一行重新嵌入一遍，会产生调用费用。
3. 执行 `strata_doctor`，`embedder_stamp` 和 `vector_coverage` 两项都应为 ok。

`strata_rebuild_index` 不带 `tenant_id` 时重建所有租户。带 `tenant_id` 时只删除并重建该租户的向量，其他租户不动。如果索引没有标记、或由别的嵌入器建成，按租户的调用会改为重建全部租户（返回 `scope: "all"` 和 `escalated_from_tenant`），因为其他租户的向量本来也不能用。更换嵌入提供方或模型后，仍需 rebuild 才能恢复向量召回（`EMBEDDER_MISMATCH`）。

## 许可

MIT — 见 [LICENSE](LICENSE)
