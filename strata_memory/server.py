"""Strata Memory MCP Server v2.0.0 — Industrial AI Memory Base.

Core philosophy: LLM decides; deterministic code executes.

Tool surface (intent-aggregated, < 15):
  Setup:   strata_init
  Write:   commit_memory, promote_session
  Read:    recall_context, expand_memory_detail
  Ops:     strata_doctor, strata_rebuild_index, strata_stats, strata_project

All descriptions follow: 作用 + 触发 + 禁忌 (three-part defensive contract).
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import (
    Resource,
    ResourcesCapability,
    ServerCapabilities,
    TextContent,
    Tool,
    ToolsCapability,
)

from .audit import AuditLogger
from .config import (
    Config,
    api_key_status,
    ensure_palace,
    is_initialized,
    is_usable_api_key,
    load_config,
    resolve_api_key,
    save_config,
    truth_db_path,
)
from .embedding import EmbeddingProvider
from .governance import ToolError, error_payload
from .ops import dump_markdown_projection, strata_doctor, strata_rebuild_index, strata_stats
from .pipeline.commit import commit_memory as pipeline_commit
from .pipeline.commit import promote_session as pipeline_promote
from .pipeline.digest import run_digest
from .pipeline.recall import expand_memory_detail as pipeline_expand
from .pipeline.recall import recall_context as pipeline_recall
from .storage.chroma import ChromaStore
from .storage.truth_store import TruthStore

# ── Global state ────────────────────────────────────────────────────────
_config: Optional[Config] = None
_embed_provider: Optional[EmbeddingProvider] = None
_chroma: Optional[ChromaStore] = None
_store: Optional[TruthStore] = None
_auditor: Optional[AuditLogger] = None

# Three-part description helper
def _d(action: str, trigger: str, forbid: str) -> str:
    return f"作用：{action}\n触发：{trigger}\n禁忌：{forbid}"


def _ensure_embed_provider(config: Config) -> Optional[EmbeddingProvider]:
    """Create embedding provider or raise ToolError with how_to_fix.

    Never silently leave provider as None for cloud providers that need a key.
    Re-reads env on every call so Hermes can hot-fix STRATA_API_KEY without
    full process restart *after* _reset_state / next tool call post-fix.
    """
    global _embed_provider
    if _embed_provider is not None:
        return _embed_provider

    cfg = config.embedding
    # Always re-resolve from env — config.json never holds full key
    key = resolve_api_key(cfg.api_key or "")
    cfg.api_key = key
    status = api_key_status(key)
    provider = (cfg.provider or "siliconflow").lower()

    needs_key = provider in {"siliconflow", "openai", "openai_compatible", "cloud"}
    if needs_key and not is_usable_api_key(key):
        raise ToolError(
            "EMBEDDING_API_KEY_MISSING",
            (
                f"Embedding provider '{provider}' has no usable API key "
                f"(status={status.get('reason')}, length={status.get('length', 0)})."
            ),
            fix=(
                "Set a full key in the MCP process environment, then restart Hermes MCP:\n"
                "  export STRATA_API_KEY='sk-...'   # full key, NOT sk-xxx...yyy redacted form\n"
                "Or put STRATA_API_KEY into ~/.hermes/.env and use the updated strata-wrapper.sh.\n"
                "Do NOT read OpenClaw memorySearch.remote.apiKey if it contains '...' "
                "(that is a UI-redacted placeholder).\n"
                "Verify: strata_doctor → embedding.api_key.usable must be true."
            ),
            retry_safe=True,
            fields={"api_key_status": status, "provider": provider},
        )

    try:
        _embed_provider = EmbeddingProvider.create(
            provider=cfg.provider,
            model=cfg.model,
            base_url=cfg.base_url,
            api_key=key,
            dimension=cfg.dimension,
        )
    except Exception as e:
        raise ToolError(
            "EMBEDDING_PROVIDER_INIT_FAILED",
            f"Failed to create embedding provider '{provider}': {e}",
            fix=(
                "Check provider/model/base_url in config. "
                "For siliconflow: provider=siliconflow, model=BAAI/bge-m3, "
                "base_url=https://api.siliconflow.cn/v1, and a valid STRATA_API_KEY."
            ),
            retry_safe=True,
            fields={"provider": provider, "error": str(e)},
        ) from e
    return _embed_provider


def _get_state(
    *,
    require_embed: bool = False,
) -> tuple[Config, TruthStore, Optional[EmbeddingProvider], Optional[ChromaStore], AuditLogger]:
    global _config, _embed_provider, _chroma, _store, _auditor
    if _config is None:
        _config = load_config()
    else:
        # Refresh key from env each time (Hermes may inject env after boot)
        refreshed = resolve_api_key(_config.embedding.api_key or "")
        if refreshed and refreshed != _config.embedding.api_key:
            _config.embedding.api_key = refreshed
            _embed_provider = None  # force recreate with new key

    palace = Path(_config.palace_path)
    if _store is None:
        ensure_palace(palace)
        _store = TruthStore(truth_db_path(palace))

    embed: Optional[EmbeddingProvider] = _embed_provider
    if require_embed or _embed_provider is None:
        try:
            embed = _ensure_embed_provider(_config)
        except ToolError:
            if require_embed:
                raise
            # Non-vector tools (doctor/stats/commit without index) may proceed
            embed = None

    if _chroma is None:
        _chroma = ChromaStore(palace / "l2_vector")
    if _auditor is None:
        _auditor = AuditLogger(palace)
    return _config, _store, embed, _chroma, _auditor


def _reset_state() -> None:
    global _config, _embed_provider, _chroma, _store, _auditor
    _config = None
    _embed_provider = None
    _chroma = None
    _store = None
    _auditor = None


def _json(data: Any) -> list[TextContent]:
    return [TextContent(type="text", text=json.dumps(data, indent=2, ensure_ascii=False))]


def _tool_error(e: Exception) -> list[TextContent]:
    if isinstance(e, ToolError):
        return _json(e.to_dict())
    return _json(error_payload(
        "INTERNAL_ERROR",
        str(e),
        fix="Inspect strata_doctor. If index-related, try strata_rebuild_index(confirm=true).",
        retry_safe=True,
    ))


# ── Server ──────────────────────────────────────────────────────────────
server = Server("strata-memory")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="strata_init",
            description=_d(
                "初始化 Memory Palace：写入配置、创建 SQLite Truth Store 与向量目录。",
                "首次使用或重置部署时调用一次。",
                "禁止在已有生产数据上重复 init 覆盖配置而不备份；禁止把 API Key 写进对话日志。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["personal", "company"],
                        "description": "personal=CBT 冷却；company=多租户+审计。",
                        "default": "personal",
                    },
                    "api_key": {
                        "type": "string",
                        "description": "Embedding API key。优先使用环境变量 STRATA_API_KEY，可省略此字段。",
                    },
                    "provider": {"type": "string", "default": "siliconflow"},
                    "model": {"type": "string", "default": "BAAI/bge-m3"},
                    "base_url": {
                        "type": "string",
                        "default": "https://api.siliconflow.cn/v1",
                    },
                    "cbt_mode": {
                        "type": "string",
                        "enum": ["passive", "active", "off"],
                        "description": "personal 默认 passive；company 默认 off。",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "company 模式必填租户 ID。",
                    },
                },
                "required": [],
            },
        ),
        Tool(
            name="commit_memory",
            description=_d(
                "将萃取后的高价值事实持久化到 SQLite Truth Store（经 Quality Kernel 校验）。",
                "跨多轮对话确认的客观事实、用户显式偏好、可复用操作规程；或需暂存的 session scratch。",
                "拒绝写入临时情绪、假设推演、密码/Token/API Key；禁止模糊时间（刚才/昨天）；"
                "严禁把未经确认的推测写成 factual_truth。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "主体 ID（三维坐标之一）。必填。",
                    },
                    "memory_type": {
                        "type": "string",
                        "enum": [
                            "factual_truth",
                            "user_preference",
                            "procedure_rule",
                            "episodic_event",
                        ],
                        "description": "严格类型；系统据此分配 TTL 与默认层级。",
                    },
                    "fact_claim": {
                        "type": "string",
                        "description": "高度压缩的第三人称事实陈述。禁止模糊时间与秘密。",
                    },
                    "confidence_score": {
                        "type": "number",
                        "minimum": 0.1,
                        "maximum": 1.0,
                        "description": "LLM 对事实真实性的自评 [0.1,1.0]。低于阈值将仅进 scratch。",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "会话 ID。scratch 或 company 隔离时建议必填。",
                    },
                    "tenant_id": {
                        "type": "string",
                        "description": "租户 ID。company 模式使用；默认取配置。",
                    },
                    "is_scratch": {
                        "type": "boolean",
                        "default": False,
                        "description": "true=仅会话暂存，需 promote_session 才晋升 durable。",
                    },
                    "room": {"type": "string", "default": "general"},
                    "context_tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "状态依赖检索标签。",
                    },
                },
                "required": ["user_id", "memory_type", "fact_claim", "confidence_score"],
            },
        ),
        Tool(
            name="promote_session",
            description=_d(
                "将会话 Scratch Buffer 中已验证记忆晋升为 durable（L0/L2）并补建向量索引。",
                "会话结束、用户确认要点、或完成任务复盘后。",
                "禁止在未验证的噪音会话上批量 promote；禁止跨 session_id 调用。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "session_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                },
                "required": ["user_id", "session_id"],
            },
        ),
        Tool(
            name="recall_context",
            description=_d(
                "渐进式召回：Hybrid RRF（向量+FTS）返回 {id, summary, score} 卡片，控制 Token。",
                "新会话开始、需要相关记忆时；默认 deep=L0+检索，shallow=仅核心画像。",
                "禁止把返回结果当作全文；需要细节时必须再调 expand_memory_detail。"
                "禁止无 query 的全库倾倒。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "query": {
                        "type": "string",
                        "description": "当前意图/问题，用于语义+全文匹配。",
                    },
                    "session_id": {"type": "string"},
                    "tenant_id": {"type": "string"},
                    "limit": {
                        "type": "integer",
                        "default": 8,
                        "minimum": 1,
                        "maximum": 20,
                    },
                    "context_depth": {
                        "type": "string",
                        "enum": ["shallow", "deep"],
                        "default": "deep",
                    },
                },
                "required": ["user_id", "query"],
            },
        ),
        Tool(
            name="expand_memory_detail",
            description=_d(
                "按 memory_id 二次拉取完整 detail（渐进披露第二阶段）。",
                "recall_context 命中卡片后，模型判断需要原文细节时。",
                "禁止猜测 id；禁止用其他 user_id 读取（硬隔离）。单次 detail 上限 4000 字符。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string"},
                    "memory_id": {
                        "type": "string",
                        "description": "来自 recall_context hits[].id",
                    },
                    "tenant_id": {"type": "string"},
                },
                "required": ["user_id", "memory_id"],
            },
        ),
        Tool(
            name="strata_doctor",
            description=_d(
                "一键巡检 SQLite SoT 与向量索引一致性（类似 git fsck）。",
                "部署后自检、召回异常、怀疑索引污染时。",
                "非对话记忆工具；不要在每轮用户闲聊时调用。",
            ),
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="strata_rebuild_index",
            description=_d(
                "清空并从 SQLite 全量重建向量索引（重建级容灾）。",
                "doctor 报告 INDEX_EMPTY/ORPHANS，或 embedding 模型/维度变更后。",
                "必须 confirm=true。仅摧毁向量伴生层，绝不删除 SQLite 真相源。"
                "禁止在无 API Key 时强行 rebuild。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "confirm": {
                        "type": "boolean",
                        "description": "确认门：必须为 true 才执行。",
                        "default": False,
                    },
                    "tenant_id": {"type": "string"},
                },
                "required": [],
            },
        ),
        Tool(
            name="strata_stats",
            description=_d(
                "打印 L0–L3 Token 水位线、类型分布与工具调用轨迹摘要。",
                "预防上下文溢出、运维巡检、裁撤低效工具前的证据采集。",
                "不要当作业务记忆检索接口。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "可选：只看该用户的层级切片。",
                    },
                },
            },
        ),
        Tool(
            name="strata_project",
            description=_d(
                "从 SQLite 生成只读 Markdown 投影（人类/Obsidian 浏览用）。",
                "需要 Git diff、人工审阅或导出可读快照时。",
                "投影不可写回；禁止把投影目录当作数据库编辑。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "可选：仅投影该用户。"},
                },
            },
        ),
        Tool(
            name="strata_digest",
            description=_d(
                "后台遗忘任务：按 TTL/分数将陈旧记忆 demote→L3 或 archive（不物理删除）。",
                "夜间 cron 或显式运维；不要在用户对话热路径自动频繁调用。",
                "dry_run=true 可先预览。禁止用此工具删除用户主动要求保留的核心身份。",
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "dry_run": {"type": "boolean", "default": True},
                },
            },
        ),
    ]


@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    resources = [
        Resource(
            uri="strata://onboarding/steps.md",
            name="Onboarding Guide",
            description="2.0 初始化与工具契约说明。",
            mimeType="text/markdown",
        ),
        Resource(
            uri="strata://stats",
            name="Memory Statistics",
            description="Truth Store + waterline JSON。",
            mimeType="application/json",
        ),
        Resource(
            uri="strata://architecture",
            name="Architecture Summary",
            description="SoT / projection / rebuildable index 说明。",
            mimeType="text/markdown",
        ),
    ]
    if is_initialized():
        resources.append(
            Resource(
                uri="strata://audit/logs",
                name="Audit Summary",
                description="最近审计与轨迹摘要。",
                mimeType="application/json",
            )
        )
    return resources


@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    t0 = time.time()
    args = arguments or {}
    status = "ok"
    err_code = ""
    try:
        if name == "strata_init":
            result = await _handle_init(args)
        elif name == "commit_memory":
            result = await _handle_commit(args)
        elif name == "promote_session":
            result = await _handle_promote(args)
        elif name == "recall_context":
            result = await _handle_recall(args)
        elif name == "expand_memory_detail":
            result = _handle_expand(args)
        elif name == "strata_doctor":
            result = _handle_doctor()
        elif name == "strata_rebuild_index":
            result = await _handle_rebuild(args)
        elif name == "strata_stats":
            result = _handle_stats(args)
        elif name == "strata_project":
            result = _handle_project(args)
        elif name == "strata_digest":
            result = _handle_digest(args)
        else:
            status = "error"
            err_code = "UNKNOWN_TOOL"
            result = error_payload(
                "UNKNOWN_TOOL",
                f"Unknown tool: {name}",
                fix=(
                    "Use one of: strata_init, commit_memory, promote_session, "
                    "recall_context, expand_memory_detail, strata_doctor, "
                    "strata_rebuild_index, strata_stats, strata_project, strata_digest."
                ),
            )
        if isinstance(result, dict) and result.get("status") == "error":
            status = "error"
            err_code = result.get("error_code", "")
        out = _json(result) if isinstance(result, dict) else result
    except Exception as e:
        status = "error"
        err_code = getattr(e, "code", "INTERNAL_ERROR")
        out = _tool_error(e)
    finally:
        try:
            cfg, store, *_ = _get_state()
            store.log_trajectory(
                name,
                tenant_id=str(args.get("tenant_id") or cfg.tenant_id or ""),
                user_id=str(args.get("user_id") or ""),
                session_id=str(args.get("session_id") or ""),
                args_digest=",".join(sorted(args.keys())),
                result_status=status,
                error_code=err_code,
                latency_ms=int((time.time() - t0) * 1000),
            )
        except Exception:
            pass
    return out


@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    if uri == "strata://onboarding/steps.md":
        return _onboarding_md()
    if uri == "strata://architecture":
        return _architecture_md()
    if uri == "strata://stats":
        return json.dumps(_handle_stats({}), indent=2, ensure_ascii=False)
    if uri == "strata://audit/logs":
        return _audit_resource()
    raise ValueError(f"Unknown resource: {uri}")


# ── Handlers ────────────────────────────────────────────────────────────

async def _handle_init(args: dict) -> dict:
    mode = args.get("mode", "personal")
    provider = args.get("provider", "siliconflow")
    model = args.get("model", "BAAI/bge-m3")
    base_url = args.get("base_url", "https://api.siliconflow.cn/v1")
    tenant_id = args.get("tenant_id", "")
    api_key = resolve_api_key(str(args.get("api_key") or ""))
    key_stat = api_key_status(api_key)

    if mode == "company" and not tenant_id:
        return error_payload(
            "TENANT_REQUIRED",
            "company mode requires tenant_id.",
            fix="Pass tenant_id='your_org_id' or use mode='personal'.",
        )

    if (provider or "siliconflow") == "siliconflow" and not is_usable_api_key(api_key):
        return error_payload(
            "EMBEDDING_API_KEY_MISSING",
            (
                "strata_init: no usable SiliconFlow API key "
                f"(status={key_stat.get('reason')}, length={key_stat.get('length', 0)})."
            ),
            fix=(
                "Pass a full api_key= OR export STRATA_API_KEY before starting Hermes. "
                "Reject keys containing '...' (OpenClaw redaction). "
                "Recommended: put STRATA_API_KEY in ~/.hermes/.env and use updated strata-wrapper.sh."
            ),
            fields={"api_key_status": key_stat},
        )

    cbt_default = args.get("cbt_mode") or ("off" if mode == "company" else "passive")
    palace_path = os.environ.get("STRATA_PALACE") or str(Path.home() / ".strata" / "palace")

    config = Config(
        mode=mode,
        tenant_id=tenant_id,
        version="2.0.0",
        storage_backend="sqlite",
        embedding={
            "provider": provider,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
            "dimension": 384,
        },
        cbt={
            "enabled": mode == "personal" and cbt_default != "off",
            "mode": cbt_default,
            "cooling_hours": 48,
            "detect_distortions": mode == "personal",
        },
        audit={
            "enabled": mode == "company",
            "log_to_db": True,
            "log_to_markdown": True,
            "retention_days": 365,
        },
        palace_path=palace_path,
    )
    palace = Path(palace_path)
    ensure_palace(palace)
    save_config(config)
    # Eager create SoT
    TruthStore(truth_db_path(palace))
    _reset_state()

    return {
        "status": "ok",
        "message": f"Strata Memory 2.0 initialized ({mode} mode).",
        "version": "2.0.0",
        "palace": palace_path,
        "truth_db": str(truth_db_path(palace)),
        "embedding": f"{provider}/{model}",
        "cbt": cbt_default,
        "tenant_id": tenant_id or None,
        "api_key_configured": is_usable_api_key(api_key),
        "api_key_status": key_stat,
        "next": [
            "strata_doctor() — confirm embedding.api_key.usable=true",
            "commit_memory(...) to write facts",
            "recall_context(...) at session start",
        ],
    }


async def _handle_commit(args: dict) -> dict:
    # Embed preferred but not hard-required: SoT write still succeeds; index may lag.
    config, store, embed, chroma, _ = _get_state(require_embed=False)
    if not is_initialized():
        return error_payload(
            "NOT_INITIALIZED",
            "Strata not initialized.",
            fix="Call strata_init(mode='personal') first (API key via STRATA_API_KEY env recommended).",
        )
    embed_warning: Optional[dict] = None
    if embed is None:
        try:
            embed = _ensure_embed_provider(config)
        except ToolError as te:
            # SoT write still proceeds; vector index skipped with explicit warning
            embed_warning = te.to_dict()
    required = ["user_id", "memory_type", "fact_claim", "confidence_score"]
    missing = [p for p in required if p not in args or args.get(p) in (None, "")]
    if missing:
        return error_payload(
            "MISSING_PARAMS",
            f"Missing: {', '.join(missing)}",
            fix=(
                "commit_memory(user_id, memory_type, fact_claim, confidence_score). "
                "memory_type ∈ factual_truth|user_preference|procedure_rule|episodic_event."
            ),
            fields={"missing": missing},
        )
    result = await pipeline_commit(
        config=config,
        store=store,
        embed_provider=embed,
        chroma=chroma,
        user_id=str(args["user_id"]),
        memory_type=str(args["memory_type"]),
        fact_claim=str(args["fact_claim"]),
        confidence_score=float(args["confidence_score"]),
        tenant_id=str(args.get("tenant_id") or config.tenant_id or ""),
        session_id=str(args.get("session_id") or ""),
        room=str(args.get("room") or "general"),
        context_tags=args.get("context_tags") or [],
        is_scratch=bool(args.get("is_scratch", False)),
    )
    if embed_warning:
        result["vector_index_warning"] = embed_warning
        result["indexed"] = False
        result["message"] = (
            (result.get("message") or "ok")
            + " | Vector index skipped: fix STRATA_API_KEY then strata_rebuild_index(confirm=true)."
        )
    return result


async def _handle_promote(args: dict) -> dict:
    config, store, embed, chroma, _ = _get_state()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    if not args.get("user_id") or not args.get("session_id"):
        return error_payload(
            "MISSING_PARAMS",
            "user_id and session_id required.",
            fix="promote_session(user_id='...', session_id='...')",
        )
    return await pipeline_promote(
        store=store,
        config=config,
        embed_provider=embed,
        chroma=chroma,
        user_id=str(args["user_id"]),
        session_id=str(args["session_id"]),
        tenant_id=str(args.get("tenant_id") or config.tenant_id or ""),
    )


async def _handle_recall(args: dict) -> dict:
    # Hybrid RRF degrades to FTS-only if embed missing; still try to init loudly.
    try:
        config, store, embed, chroma, _ = _get_state(require_embed=False)
        if embed is None:
            try:
                embed = _ensure_embed_provider(config)
            except ToolError:
                embed = None  # FTS-only fallback
    except ToolError as e:
        return e.to_dict()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    if not args.get("user_id") or not args.get("query"):
        return error_payload(
            "MISSING_PARAMS",
            "user_id and query required.",
            fix="recall_context(user_id='...', query='coding preferences')",
        )
    return await pipeline_recall(
        config=config,
        store=store,
        embed_provider=embed,
        chroma=chroma,
        user_id=str(args["user_id"]),
        query=str(args["query"]),
        tenant_id=str(args.get("tenant_id") or config.tenant_id or ""),
        session_id=str(args.get("session_id") or ""),
        limit=int(args.get("limit") or 8),
        context_depth=str(args.get("context_depth") or "deep"),
    )


def _handle_expand(args: dict) -> dict:
    config, store, *_ = _get_state()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    if not args.get("user_id") or not args.get("memory_id"):
        return error_payload(
            "MISSING_PARAMS",
            "user_id and memory_id required.",
            fix="expand_memory_detail(user_id='...', memory_id='<id from recall>')",
        )
    return pipeline_expand(
        store=store,
        memory_id=str(args["memory_id"]),
        user_id=str(args["user_id"]),
        tenant_id=str(args.get("tenant_id") or config.tenant_id or ""),
        config=config,
    )


def _handle_doctor() -> dict:
    config, store, _, chroma, _ = _get_state()
    return strata_doctor(config=config, store=store, chroma=chroma)


async def _handle_rebuild(args: dict) -> dict:
    try:
        config, store, embed, chroma, _ = _get_state(require_embed=True)
    except ToolError as e:
        return e.to_dict()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    if embed is None:
        return error_payload(
            "NO_EMBEDDING_PROVIDER",
            "Embedding provider unavailable (missing or redacted API key).",
            fix=(
                "export STRATA_API_KEY='sk-...' with the FULL key (no '...'), "
                "update strata-wrapper.sh, restart Hermes MCP, then strata_doctor."
            ),
        )
    # rebuild returns new chroma — reset global so next call reopens
    result = await strata_rebuild_index(
        config=config,
        store=store,
        embed_provider=embed,
        chroma=chroma,  # type: ignore[arg-type]
        confirm=bool(args.get("confirm", False)),
        tenant_id=str(args.get("tenant_id") or config.tenant_id or ""),
    )
    if result.get("status") == "ok":
        global _chroma
        _chroma = None  # force reopen on wiped dir
    return result


def _handle_stats(args: dict) -> dict:
    config, store, _, chroma, _ = _get_state()
    return strata_stats(
        config=config,
        store=store,
        chroma=chroma,
        user_id=str(args.get("user_id") or ""),
    )


def _handle_project(args: dict) -> dict:
    config, store, *_ = _get_state()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    palace = Path(config.palace_path)
    return dump_markdown_projection(
        store,
        palace,
        tenant_id=config.tenant_id or "",
        user_id=args.get("user_id") or None,
    )


def _handle_digest(args: dict) -> dict:
    config, store, *_ = _get_state()
    if not is_initialized():
        return error_payload("NOT_INITIALIZED", "Not initialized.", fix="Run strata_init first.")
    return run_digest(store, config, dry_run=bool(args.get("dry_run", True)))


def _onboarding_md() -> str:
    return """# Strata Memory 2.0 — Agent Onboarding

## Architecture (read this)

- **SQLite** = Single Source of Truth (`palace/truth/strata.db`)
- **ChromaDB** = rebuildable vector companion (`palace/l2_vector/`)
- **Markdown** = read-only projection (`strata_project`)

## First-time setup

1. Prefer env: `STRATA_API_KEY`, optional `STRATA_PALACE`
2. Call `strata_init(mode="personal")` or company with `tenant_id`
3. `strata_doctor()` — expect healthy / address warnings
4. Write: `commit_memory(user_id, memory_type, fact_claim, confidence_score)`
5. Read: `recall_context` → optional `expand_memory_detail`

## Memory types

| type | meaning | default layer |
|------|---------|---------------|
| factual_truth | verified objective fact | L0 |
| user_preference | stable preference | L0 |
| procedure_rule | how-to / SOP | L0 |
| episodic_event | time-bound episode | L2 (TTL 90d) |

## Forbidden writes

- secrets / API keys / passwords
- pure emotion without fact
- speculation as factual_truth
- relative time (刚才 / yesterday) — use ISO dates

## Progressive recall

Never dump full library. `recall_context` returns cards; expand only what you need.
"""


def _architecture_md() -> str:
    return """# Strata Memory 2.0 Architecture

```
LLM ──commit_memory──► Quality Kernel ──► CBT Middleware ──► SQLite (SoT)
                                              │
                                              └─► Chroma (companion, rebuildable)

LLM ──recall_context──► Hybrid RRF (vector+FTS) ──► {id,summary,score}
LLM ──expand_memory_detail(id)──► full detail (scope-checked)

Ops: doctor | rebuild_index | stats | project | digest
```

Principle: **LLM decides; deterministic code owns metadata, TTL, safety, and storage.**
"""


def _audit_resource() -> str:
    config, store, *_ = _get_state()
    return json.dumps(
        {
            "trajectory": store.trajectory_summary(40),
            "stats": store.stats(),
            "mode": config.mode,
        },
        indent=2,
        ensure_ascii=False,
    )


async def run() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="strata-memory",
                server_version="2.0.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability(listChanged=None),
                    resources=ResourcesCapability(listChanged=None),
                ),
            ),
        )
