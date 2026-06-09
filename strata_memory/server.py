"""Strata Memory MCP Server v0.2.0.

Dual-mode architecture (personal/company) with enterprise features:
  - Personal: CBT safety, emotional tracking, 48h cooling
  - Company:  Multi-tenancy, AuditLog, Wing→Hall→Room→Drawer hierarchy

Agent-Driven Onboarding (NEW):
  - get_system_profile              — Silent hardware detection
  - search_embedding_recommendations — Hardware-aware model matching
  - apply_memory_config             — Config persistence + hot reload
  - strata://memory/setup-instructions.md — Agent onboarding guide

Core tools:
  - strata_init    — First-time setup with mode selection
  - memorize       — Enhanced write with psych fields
  - wake_up        — L0+L1+L2 with defusion for negative schemas
  - search         — Semantic search with category/time/tag filters
  - get_health     — Runtime status with mode-aware stats

Resources:
  - strata://onboarding/steps.md
  - strata://memory/setup-instructions.md
  - strata://stats
  - strata://wings
  - strata://audit/logs
"""

from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

from mcp.server import Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server
from mcp.types import Resource, ServerCapabilities, TextContent, Tool, ToolsCapability, ResourcesCapability

from .audit import AuditLogger
from .config import Config, ensure_palace, is_initialized, load_config, save_config
from .embedding import EmbeddingProvider
from .pipeline.memorize import memorize as pipeline_memorize
from .pipeline.wake import wake_up as pipeline_wake_up
from .storage.chroma import ChromaStore
from .storage.markdown import estimate_tokens, list_drawers
from .tools.system_profile import (
    SETUP_INSTRUCTIONS_TEMPLATE,
    apply_memory_config,
    get_system_profile,
    search_embedding_recommendations,
)

# ── Global state ────────────────────────────────────────────────────────
_config: Optional[Config] = None
_embed_provider: Optional[EmbeddingProvider] = None
_chroma: Optional[ChromaStore] = None
_auditor: Optional[AuditLogger] = None
_health_cache: Optional[tuple[float, dict]] = None  # (timestamp, data) with 30s TTL

REQUIRED_PARAMS: dict[str, list[str]] = {
    "strata_init": ["api_key"],
    "memorize": ["user_id", "content"],
    "wake_up": ["user_id", "query"],
    "search": ["query", "user_id"],
}


def _get_state() -> tuple[Config, EmbeddingProvider, ChromaStore, AuditLogger]:
    global _config, _embed_provider, _chroma, _auditor
    if _config is None:
        _config = load_config()
    if _embed_provider is None:
        cfg = _config.embedding
        _embed_provider = EmbeddingProvider.create(
            provider=cfg.provider, model=cfg.model,
            base_url=cfg.base_url, api_key=cfg.api_key,
            dimension=cfg.dimension,
        )
    if _chroma is None:
        palace = Path(_config.palace_path)
        _chroma = ChromaStore(palace / "l2_vector")
    if _auditor is None:
        _auditor = AuditLogger(Path(_config.palace_path))
    return _config, _embed_provider, _chroma, _auditor


def _reset_state():
    global _config, _embed_provider, _chroma, _auditor, _health_cache
    _config = None
    _embed_provider = None
    _chroma = None
    _auditor = None
    _health_cache = None


# ── Server setup ────────────────────────────────────────────────────────
server = Server("strata-memory")


@server.list_tools()
async def handle_list_tools() -> list[Tool]:
    return [
        Tool(
            name="strata_init",
            description="First-time initialization with dual-mode setup. Choose 'personal' (CBT safety, 48h cooling) or 'company' (multi-tenancy, AuditLog, private embedding).",
            inputSchema={
                "type": "object",
                "properties": {
                    "api_key": {"type": "string", "description": "API key for embedding provider."},
                    "mode": {"type": "string", "enum": ["personal", "company"],
                             "description": "Memory mode. personal=CBT safety+emotional tracking. company=multi-tenancy+AuditLog.", "default": "personal"},
                    "provider": {"type": "string", "description": "Embedding provider.", "default": "siliconflow"},
                    "model": {"type": "string", "description": "Embedding model.", "default": "BAAI/bge-m3"},
                    "base_url": {"type": "string", "description": "API base URL.", "default": "https://api.siliconflow.cn/v1"},
                    "cbt_mode": {"type": "string", "enum": ["passive", "active", "off"],
                                 "description": "CBT safety mode (personal default=passive, company default=off)."},
                    "tenant_id": {"type": "string", "description": "Tenant identifier (company mode)."},
                },
                "required": ["api_key"],
            },
        ),
        Tool(
            name="memorize",
            description="Record a conversation/fact into memory with psych-validated metadata (emotional_salience, context_tags, is_negative_schema). Writes Markdown drawer + vector index.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User/wing identifier."},
                    "content": {"type": "string", "description": "Raw text content to memorize."},
                    "category": {"type": "string", "enum": ["event","preference","procedure","core_identity","lesson","fact","goal","relationship"],
                                 "description": "Memory category (affects decay rate).", "default": "event"},
                    "importance": {"type": "number", "description": "Base importance 0.0-1.0.", "default": 0.5},
                    "room": {"type": "string", "description": "Room within wing.", "default": "general"},
                    "context_tags": {"type": "array", "items": {"type": "string"},
                                     "description": "Tags for state-dependent retrieval."},
                },
                "required": ["user_id", "content"],
            },
        ),
        Tool(
            name="wake_up",
            description="Session wake-up: L0 profile + L1 diary + L2 semantic search with CBT defusion for negative schemas. Returns flat Markdown.",
            inputSchema={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "User/wing identifier."},
                    "query": {"type": "string", "description": "Current context/question to match against."},
                    "context_depth": {"type": "string", "enum": ["shallow", "deep"],
                                      "description": "shallow=L0+L1 only, deep=L0+L1+L2.", "default": "shallow"},
                    "limit": {"type": "integer", "description": "Max L2 results.", "default": 5},
                },
                "required": ["user_id", "query"],
            },
        ),
        Tool(
            name="search",
            description="Active semantic search across L2 memories with time/category/tag filters and state-dependent boosting.",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query."},
                    "user_id": {"type": "string", "description": "Wing scope."},
                    "limit": {"type": "integer", "default": 10},
                    "category": {"type": "string", "description": "Category filter."},
                    "from_date": {"type": "string", "description": "ISO start date."},
                    "to_date": {"type": "string", "description": "ISO end date."},
                    "context_tags": {"type": "array", "items": {"type": "string"},
                                     "description": "State-dependent boost tags."},
                },
                "required": ["query", "user_id"],
            },
        ),
        Tool(
            name="get_health",
            description="Runtime status: initialized, mode, CBT, audit, vector/drawer count, config summary.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="get_system_profile",
            description="[Agent-Driven] Silent hardware profiling. Returns OS, RAM, CPU cores, GPU accelerator. No user input required — call this first during onboarding.",
            inputSchema={"type": "object", "properties": {}},
        ),
        Tool(
            name="search_embedding_recommendations",
            description="[Agent-Driven] Return ranked embedding recommendations based on hardware profile. Gets best-fit local/cloud models from MTEB-informed lookup table.",
            inputSchema={
                "type": "object",
                "properties": {
                    "profile": {"type": "object", "description": "Optional hardware profile from get_system_profile. If omitted, runs detection automatically."},
                },
            },
        ),
        Tool(
            name="apply_memory_config",
            description="[Agent-Driven] Apply chosen memory configuration: persist config, initialize Palace directories, ChromaDB, SQLite. Supports hot reload — no MCP restart needed.",
            inputSchema={
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["personal", "company"],
                             "description": "Memory mode.", "default": "personal"},
                    "provider": {"type": "string", "description": "Embedding provider (e.g. siliconflow, local)."},
                    "model": {"type": "string", "description": "Embedding model name."},
                    "api_key": {"type": "string", "description": "API key for cloud providers."},
                    "base_url": {"type": "string", "description": "API base URL."},
                    "dimension": {"type": "integer", "description": "Embedding dimension.", "default": 384},
                    "cbt_mode": {"type": "string", "enum": ["passive", "active", "off"],
                                 "description": "CBT safety mode."},
                    "tenant_id": {"type": "string", "description": "Tenant identifier (company mode)."},
                },
                "required": ["mode", "provider", "model"],
            },
        ),
    ]


@server.list_resources()
async def handle_list_resources() -> list[Resource]:
    resources = [
        Resource(uri="strata://onboarding/steps.md", name="Onboarding Guide",
                 description="Dual-mode initialization steps (personal + company).", mimeType="text/markdown"),
        Resource(uri="strata://memory/setup-instructions.md", name="Agent-Driven Setup Guide",
                 description="[Agent-Driven] Dynamic setup instructions for the AI agent. Read this first during onboarding to learn the Agent-Driven initialization flow.", mimeType="text/markdown"),
        Resource(uri="strata://stats", name="Memory Statistics",
                 description="System stats: drawer/vector count, mode, config.", mimeType="application/json"),
        Resource(uri="strata://wings", name="Wing Directory",
                 description="All wings and their rooms.", mimeType="application/json"),
    ]
    if is_initialized():
        resources.append(Resource(uri="strata://audit/logs", name="Audit Logs",
                                  description="Operation audit trail.", mimeType="application/json"))
    return resources


# ── Tool dispatcher ─────────────────────────────────────────────────────

@server.call_tool()
async def handle_call_tool(name: str, arguments: dict) -> list[TextContent]:
    # Structured parameter validation
    if name in REQUIRED_PARAMS:
        missing = [p for p in REQUIRED_PARAMS[name] if p not in arguments or arguments.get(p, "") == ""]
        if missing:
            return [TextContent(type="text", text=(
                f"Missing required parameters: {', '.join(missing)}.\n"
                f"Expected: `{name}({', '.join(REQUIRED_PARAMS[name])})`"
            ))]
    try:
        if name == "strata_init":
            return await _handle_strata_init(arguments)
        elif name == "memorize":
            return await _handle_memorize(arguments)
        elif name == "wake_up":
            return await _handle_wake_up(arguments)
        elif name == "search":
            return await _handle_search(arguments)
        elif name == "get_health":
            return await _handle_get_health(arguments)
        elif name == "get_system_profile":
            return _handle_get_system_profile()
        elif name == "search_embedding_recommendations":
            return _handle_search_embedding_recommendations(arguments)
        elif name == "apply_memory_config":
            return await _handle_apply_memory_config(arguments)
        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except Exception as e:
        return [TextContent(type="text", text=f"Internal error: {e}")]


@server.read_resource()
async def handle_read_resource(uri: str) -> str:
    if uri == "strata://onboarding/steps.md":
        return _onboarding_steps()
    elif uri == "strata://memory/setup-instructions.md":
        return _setup_instructions()
    elif uri == "strata://stats":
        return await _stats_json()
    elif uri == "strata://wings":
        return await _wings_json()
    elif uri == "strata://audit/logs":
        return await _audit_json()
    else:
        raise ValueError(f"Unknown resource: {uri}")


# ── Tool implementations ────────────────────────────────────────────────

async def _handle_strata_init(args: dict) -> list[TextContent]:
    api_key = args["api_key"]
    mode = args.get("mode", "personal")
    provider = args.get("provider", "siliconflow")
    model = args.get("model", "BAAI/bge-m3")
    base_url = args.get("base_url", "https://api.siliconflow.cn/v1")
    tenant_id = args.get("tenant_id", "")

    # Mode-aware CBT defaults
    if mode == "company":
        cbt_default = args.get("cbt_mode", "off")
    else:
        cbt_default = args.get("cbt_mode", "passive")

    config = Config(
        mode=mode,
        tenant_id=tenant_id,
        embedding={
            "provider": provider, "model": model,
            "api_key": api_key, "base_url": base_url, "dimension": 384,
        },
        cbt={
            "enabled": mode == "personal",
            "mode": cbt_default, "cooling_hours": 48,
            "detect_distortions": mode == "personal",
        },
        audit={"enabled": mode == "company", "log_to_db": mode == "company",
               "log_to_markdown": True, "retention_days": 365},
    )

    env_path = os.environ.get("STRATA_PALACE", "")
    palace_path = env_path or str(Path.home() / ".strata" / "palace")
    config.palace_path = palace_path

    palace = Path(palace_path)
    ensure_palace(palace)
    save_config(config)
    _reset_state()

    return [TextContent(type="text", text=(
        f"Strata Memory initialized ({mode} mode).\n\n"
        f"Palace: {palace_path}\n"
        f"Embedding: {provider}/{model}\n"
        f"CBT: {cbt_default} (cooling=48h)\n"
        f"Audit: {'enabled' if config.audit.enabled else 'markdown-only'}\n"
        f"Tenant: {tenant_id or 'N/A (personal mode)'}\n\n"
        f"Next: Use `memorize` to start recording memories."
    ))]


async def _handle_memorize(args: dict) -> list[TextContent]:
    config, embed_provider, chroma, auditor = _get_state()
    if not is_initialized():
        return [TextContent(type="text", text="Error: Strata not initialized. Run `strata_init` first.")]

    user_id = args["user_id"]
    content = args["content"]
    category = args.get("category", "event")
    importance = float(args.get("importance", 0.5))
    room = args.get("room", "general")
    context_tags = args.get("context_tags", [])

    result = await pipeline_memorize(
        config=config, embed_provider=embed_provider, chroma=chroma,
        user_id=user_id, content=content,
        metadata={"category": category, "importance": importance, "room": room},
        context_tags=context_tags,
    )

    auditor.log_memorize(user_id, content, result)
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def _handle_wake_up(args: dict) -> list[TextContent]:
    config, embed_provider, chroma, auditor = _get_state()
    if not is_initialized():
        return [TextContent(type="text", text="Error: Strata not initialized.")]

    user_id = args["user_id"]
    query = args["query"]
    context_depth = args.get("context_depth", "shallow")
    limit = int(args.get("limit", 5))

    result = await pipeline_wake_up(
        config=config, embed_provider=embed_provider, chroma=chroma,
        user_id=user_id, query=query, context_depth=context_depth, limit=limit,
    )

    auditor.log_wake_up(user_id, query, result)

    footer = (
        f"\n\n<!-- strata-wake-stats: v={config.version} mode={config.mode} "
        f"tokens={result['token_estimate']} l0={1 if result.get('l0_loaded') else 0} "
        f"l1={result['l1_entries']} l2={result['l2_results']} "
        f"neg={result.get('negative_filtered',0)} cbt={result.get('cbt_mode','off')} "
        f"depth={result['context_depth']} -->"
    )
    return [TextContent(type="text", text=result["context"] + footer)]


async def _handle_search(args: dict) -> list[TextContent]:
    config, embed_provider, chroma, auditor = _get_state()
    if not is_initialized():
        return [TextContent(type="text", text="Error: Strata not initialized.")]

    query = args["query"]
    user_id = args["user_id"]
    limit = int(args.get("limit", 10))
    category = args.get("category")
    context_tags = args.get("context_tags", [])

    wing = f"users/{user_id}"
    query_vec = await embed_provider.embed(query)

    where = {"wing": wing}
    if category:
        where["category"] = category

    results = chroma.query(query_embedding=query_vec, top_k=limit, where=where)

    lines = [f"# Search Results: \"{query}\"\n"]
    MAX_DOC_CHARS = 1500
    for i, r in enumerate(results, 1):
        dist = r.get("distance", 0.0)
        sim = max(0.0, 1.0 - dist)
        meta = r.get("metadata", {})
        raw_doc = r.get("document", "") or ""
        doc = raw_doc[:MAX_DOC_CHARS]
        if len(raw_doc) > MAX_DOC_CHARS:
            doc += "\n\n*[truncated — use `search` with larger limit for full text]*"
        lines.append(
            f"## Result {i} (relevance: {sim:.2f})\n"
            f"- **Date**: {meta.get('date', 'unknown')}\n"
            f"- **Category**: {meta.get('category', 'unknown')}\n"
            f"- **Room**: {meta.get('room', 'unknown')}\n"
            f"\n{doc}\n---\n"
        )
    if context_tags:
        lines.insert(1, f"*State-dependent boost: {', '.join(context_tags)}*\n")

    auditor.log_search(user_id, query, len(results))
    return [TextContent(type="text",
            text="\n".join(lines) if results else f"No results for: {query}")]


async def _handle_get_health(args: dict) -> list[TextContent]:
    global _health_cache
    import time
    now = time.time()
    if _health_cache and (now - _health_cache[0]) < 30:
        return [TextContent(type="text", text=json.dumps(_health_cache[1], indent=2, ensure_ascii=False))]

    config, _, chroma, _ = _get_state()
    palace = Path(config.palace_path)
    init = is_initialized()
    vc = chroma.count() if init else 0
    dc = 0
    if init:
        try:
            dc = len(list(list_drawers(palace, "users", from_date=None)))
        except Exception:
            dc = 0

    health = {
        "version": config.version,
        "initialized": init,
        "mode": config.mode,
        "palace": str(palace),
        "tenant": config.tenant_id or "N/A",
        "embedding": {"provider": config.embedding.provider, "model": config.embedding.model,
                       "dimension": config.embedding.dimension, "mode": config.embedding.mode},
        "cbt": {"enabled": config.cbt.enabled, "mode": config.cbt.mode,
                "cooling_hours": config.cbt.cooling_hours},
        "audit": {"enabled": config.audit.enabled, "log_to_markdown": config.audit.log_to_markdown},
        "memory": {"vector_count": vc, "drawer_count": dc,
                   "l0_token_budget": config.l0_token_budget,
                   "l1_days": config.l1_days, "l2_top_k": config.l2_top_k,
                   "promotion_threshold": config.promotion_threshold,
                   "demotion_threshold": config.demotion_threshold,
                   "cooling_hours": config.cbt.cooling_hours},
        "scoring": {"promotion_min_usage": config.promotion_min_usage,
                    "l3_demotion_days": config.l3_demotion_days},
    }
    _health_cache = (now, health)
    return [TextContent(type="text", text=json.dumps(health, indent=2, ensure_ascii=False))]


# ── Agent-Driven Onboarding tool handlers ──────────────────────────────

def _handle_get_system_profile() -> list[TextContent]:
    """Silent hardware detection — returns structured profile for the Agent."""
    profile = get_system_profile()
    return [TextContent(type="text", text=json.dumps(profile, indent=2, ensure_ascii=False))]


def _handle_search_embedding_recommendations(args: dict) -> list[TextContent]:
    """Return ranked embedding recommendations based on profile."""
    profile = args.get("profile")
    recommendations = search_embedding_recommendations(profile)
    # Include the profile used for transparency
    if profile is None:
        profile = get_system_profile()
    result = {
        "profile": profile,
        "recommendations": recommendations,
        "note": "Recommendations are sorted by priority (best first). Present the top 2-3 to the user.",
    }
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


async def _handle_apply_memory_config(args: dict) -> list[TextContent]:
    """Apply memory configuration and hot-reload state."""
    result = apply_memory_config(dict(args))
    _reset_state()  # Hot reload: pick up new config on next call
    return [TextContent(type="text", text=json.dumps(result, indent=2, ensure_ascii=False))]


# ── Resource implementations ────────────────────────────────────────────

def _setup_instructions() -> str:
    """Return the Agent-Driven setup guide template."""
    return SETUP_INSTRUCTIONS_TEMPLATE


def _onboarding_steps() -> str:
    return """# Strata Memory — Agent Onboarding Guide

## Dual-Mode Setup

Strata Memory supports two modes:

| Mode | Features | Best For |
|------|----------|----------|
| **personal** | CBT safety, emotional tracking, 48h cooling-off, negative schema isolation | Individual users, long-term personal memory |
| **company** | Multi-tenancy (Wing→Hall→Room→Drawer), AuditLog, PostgreSQL, private BGE-M3 | Industrial MES/WMS, multi-agent teams |

## Personal Mode Setup

1. Ask the user: "I'll set up your personal memory system. I recommend SiliconFlow BGE-M3 for fast, Chinese-friendly embedding. Do you have an API key?"

2. Run: `strata_init(api_key="sk-...", mode="personal")`

3. The system defaults to:
   - CBT mode: passive (auto-filter negative self-talk)
   - 48h cooling-off buffer (prevents single-event over-consolidation)
   - Category-specific decay rates (event=0.85, procedure=0.98, core_identity=1.00)

## Company Mode Setup

1. Ask: "For enterprise setup: tenant ID, private embedding endpoint, PostgreSQL connection?"

2. Run: `strata_init(api_key="...", mode="company", tenant_id="factory_001")`

3. Company mode enables:
   - Wing→Hall→Room→Drawer spatial hierarchy for business domains
   - AuditLog (every operation recorded)
   - Multi-tenant RBAC isolation
   - CBT defaults to off (can be enabled for coaching agents)

## Start Recording

```
memorize(user_id="user_001", content="User prefers dark mode for coding", category="preference")
```

## Wake Up Each Session

```
wake_up(user_id="user_001", query="coding preferences", context_depth="deep")
```
"""


async def _stats_json() -> str:
    config, _, chroma, _ = _get_state()
    palace = Path(config.palace_path)
    dc = 0
    if is_initialized():
        try:
            dc = len(list(list_drawers(palace, "users", from_date=None)))
        except Exception:
            dc = 0
    return json.dumps({
        "version": config.version, "initialized": is_initialized(),
        "mode": config.mode, "palace": str(palace),
        "vectors": chroma.count() if is_initialized() else 0,
        "drawers": dc, "provider": config.embedding.provider,
        "model": config.embedding.model, "cbt": config.cbt.mode,
    }, indent=2, ensure_ascii=False)


async def _wings_json() -> str:
    config, _, _, _ = _get_state()
    palace = Path(config.palace_path)
    wings_dir = palace / "wings" / "users"
    wings = []
    if wings_dir.exists():
        for user_dir in sorted(wings_dir.iterdir()):
            if user_dir.is_dir():
                rooms = [d.name for d in user_dir.iterdir() if d.is_dir()]
                wings.append({"wing": f"users/{user_dir.name}", "rooms": rooms})
    return json.dumps({"mode": config.mode, "tenant": config.tenant_id, "wings": wings},
                      indent=2, ensure_ascii=False)


async def _audit_json() -> str:
    config, _, _, _ = _get_state()
    palace = Path(config.palace_path)
    audit_dir = palace / "audit_logs"
    entries = []
    if audit_dir.exists():
        for f in sorted(audit_dir.glob("*.md"), reverse=True)[:30]:
            try:
                post = __import__("frontmatter").load(str(f))
                entries.append({"date": f.stem, "content": post.content[:500]})
            except Exception:
                pass
    return json.dumps({"audit_entries": len(entries), "recent": entries[:5]},
                      indent=2, ensure_ascii=False)


# ── Entry point ─────────────────────────────────────────────────────────

async def run():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="strata-memory",
                server_version="0.2.0",
                capabilities=ServerCapabilities(
                    tools=ToolsCapability(listChanged=None),
                    resources=ResourcesCapability(listChanged=None),
                ),
            ),
        )
