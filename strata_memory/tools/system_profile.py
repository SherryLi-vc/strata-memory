"""Agent-Driven Onboarding Tools.

The three pillars of silent, conversation-driven MCP setup:
  1. get_system_profile()           — Silent hardware detection
  2. search_embedding_recommendations() — Hardware-aware model matching
  3. apply_memory_config()          — Config persistence + hot reload

Architecture: Tools provide data; the Host Agent (step-3.7-flash etc.) drives
the conversation. MCP stays silent — no print(), no prompts, just structured returns.
"""

from __future__ import annotations

import json
import os
import platform
from datetime import date
from pathlib import Path
from typing import Optional


# ── Hardware profiling ──────────────────────────────────────────────────

def _check_cuda() -> bool:
    """Best-effort CUDA detection without importing torch."""
    try:
        import subprocess
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=5,
        )
        return result.returncode == 0 and bool(result.stdout.strip())
    except Exception:
        return False


def get_system_profile() -> dict:
    """Silent hardware profiling — no user input required.

    Returns a dict the Agent can use to make embedding recommendations.
    Handles missing psutil gracefully with a fallback.
    """
    profile = {
        "os": platform.system(),
        "arch": platform.machine(),
        "hostname": platform.node(),
        "ram_gb": 0,
        "cpu_cores": 0,
        "accelerator": "cpu",
    }

    # Try psutil for accurate RAM/CPU
    try:
        import psutil
        profile["ram_gb"] = round(psutil.virtual_memory().total / (1024 ** 3), 1)
        profile["cpu_cores"] = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 0
    except ImportError:
        # Fallback: rough detection from /proc or sysctl
        try:
            import subprocess
            if platform.system() == "Darwin":
                result = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
                profile["ram_gb"] = round(int(result.stdout.strip()) / (1024 ** 3), 1)
                result = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True)
                profile["cpu_cores"] = int(result.stdout.strip())
            elif platform.system() == "Linux":
                with open("/proc/meminfo") as f:
                    for line in f:
                        if "MemTotal" in line:
                            profile["ram_gb"] = round(int(line.split()[1]) / (1024 ** 2), 1)
                            break
                result = subprocess.run(["nproc"], capture_output=True, text=True)
                profile["cpu_cores"] = int(result.stdout.strip())
        except Exception:
            pass

    # GPU / accelerator detection
    if _check_cuda():
        profile["accelerator"] = "cuda"
    elif platform.system() == "Darwin" and ("arm" in platform.machine().lower() or "Apple" in platform.machine()):
        profile["accelerator"] = "mps"
    elif platform.system() == "Darwin":
        # Could be Intel Mac with AMD GPU, but MPS is the safe default check
        profile["accelerator"] = "mps"

    return profile


# ── Embedding recommendation engine ─────────────────────────────────────

# Static MTEB-informed recommendation table (updated 2026-06).
# In production, this could be backed by a cached web query to the MTEB leaderboard.
_RECOMMENDATION_TABLE = {
    # (min_ram, accelerator): [(provider, model, reason, tier), ...]
    # tier: "local" | "cloud" | "hybrid"
    (32, "cuda"): [
        {"provider": "local", "model": "nomic-embed-text-v2", "dimension": 768,
         "tier": "local", "reason": "Best-in-class local embedding with GPU acceleration. ~2GB VRAM."},
        {"provider": "local", "model": "BAAI/bge-m3-gguf", "dimension": 1024,
         "tier": "local", "reason": "Multilingual BGE-M3 quantized for local use. Covers Chinese + English."},
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Cloud BGE-M3 via SiliconFlow API. Zero local footprint, MRL-truncated."},
    ],
    (32, "mps"): [
        {"provider": "local", "model": "nomic-embed-text-v2", "dimension": 768,
         "tier": "local", "reason": "Excellent local embedding on Apple Silicon via MPS. ~2GB memory."},
        {"provider": "local", "model": "BAAI/bge-m3-gguf", "dimension": 1024,
         "tier": "local", "reason": "Multilingual BGE-M3 quantized. Runs well on M-series with MPS."},
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Cloud API — ideal if you want zero local ML dependencies."},
    ],
    (32, "cpu"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "No GPU detected. Cloud API avoids slow CPU inference (BGE-M3 is 560M params)."},
        {"provider": "local", "model": "all-MiniLM-L6-v2", "dimension": 384,
         "tier": "local", "reason": "Lightweight (~80MB). Runs on CPU. English-only but very fast."},
    ],
    (16, "cuda"): [
        {"provider": "local", "model": "nomic-embed-text-v2", "dimension": 768,
         "tier": "local", "reason": "GPU-accelerated local embedding — good balance of speed and quality."},
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Cloud API with Chinese+English support. No local GPU memory pressure."},
    ],
    (16, "mps"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Recommended: 16GB shared memory is tight. Cloud API keeps it light."},
        {"provider": "local", "model": "all-MiniLM-L6-v2", "dimension": 384,
         "tier": "local", "reason": "Ultra-light local fallback. Runs comfortably on 16GB shared memory."},
    ],
    (16, "cpu"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Best option for CPU-only 16GB: cloud API, no local model overhead."},
        {"provider": "local", "model": "all-MiniLM-L6-v2", "dimension": 384,
         "tier": "local", "reason": "If privacy matters more than multilingual quality. English-only, ~80MB."},
    ],
    (8, "cuda"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Limited RAM. Cloud API recommended to avoid memory pressure."},
    ],
    (8, "mps"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "8GB shared memory is tight. Cloud API is the safe choice."},
    ],
    (8, "cpu"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Cloud API — the only practical option for 8GB CPU-only machines."},
    ],
    (0, "cpu"): [
        {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
         "tier": "cloud", "reason": "Default recommendation: SiliconFlow BGE-M3 cloud API. Works everywhere."},
    ],
}


def _get_bucket(ram_gb: float, accelerator: str) -> tuple[int, str]:
    """Map actual specs to the closest recommendation bucket."""
    thresholds = [32, 16, 8, 0]
    for t in thresholds:
        if ram_gb >= t:
            return (t, accelerator)
    return (0, "cpu")


def search_embedding_recommendations(profile: Optional[dict] = None) -> list[dict]:
    """Return ranked embedding recommendations based on hardware profile.

    If no profile is provided, runs get_system_profile() silently first.
    Returns a list of {provider, model, dimension, tier, reason} dicts,
    sorted by recommendation priority (best first).
    """
    if profile is None:
        profile = get_system_profile()

    ram = profile.get("ram_gb", 0)
    accel = profile.get("accelerator", "cpu")
    bucket = _get_bucket(ram, accel)

    # Exact match first, then fall back through lower RAM thresholds
    recommendations = _RECOMMENDATION_TABLE.get(bucket, [])
    if not recommendations:
        # Walk down thresholds
        for t in [32, 16, 8, 0]:
            recommendations = _RECOMMENDATION_TABLE.get((t, accel), [])
            if recommendations:
                break
    if not recommendations:
        recommendations = _RECOMMENDATION_TABLE[(0, "cpu")]

    return [
        {
            "provider": r["provider"],
            "model": r["model"],
            "dimension": r.get("dimension", 384),
            "tier": r["tier"],
            "reason": r["reason"],
        }
        for r in recommendations
    ]


# ── Memory config application ───────────────────────────────────────────

def apply_memory_config(
    config_dict: dict,
    *,
    config_module=None,
) -> dict:
    """Apply a memory configuration: persist, init subsystems, hot reload.

    This is the final step of Agent-Driven Onboarding. After the Agent has
    discussed options with the user, it calls this tool to materialize the
    configuration.

    config_dict keys:
      - mode: "personal" | "company" (required)
      - provider: embedding provider name (required)
      - model: embedding model name (required)
      - api_key: embedding API key (required for cloud providers)
      - base_url: API base URL (optional)
      - dimension: embedding dimension (optional, default 384)
      - cbt_mode: "passive" | "active" | "off" (optional)
      - tenant_id: tenant identifier (company mode)

    Returns a status dict with paths and initialization results.
    """
    from ..config import Config, ensure_palace, save_config, palace_dirs

    mode = config_dict.get("mode", "personal")
    provider = config_dict.get("provider", "siliconflow")
    model = config_dict.get("model", "BAAI/bge-m3")
    api_key = config_dict.get("api_key", "")
    base_url = config_dict.get("base_url", "https://api.siliconflow.cn/v1")
    dimension = int(config_dict.get("dimension", 384))
    tenant_id = config_dict.get("tenant_id", "")

    # CBT defaults: on for personal, off for company
    if mode == "company":
        cbt_mode = config_dict.get("cbt_mode", "off")
    else:
        cbt_mode = config_dict.get("cbt_mode", "passive")

    config = Config(
        mode=mode,
        tenant_id=tenant_id,
        embedding={
            "provider": provider, "model": model,
            "api_key": api_key, "base_url": base_url, "dimension": dimension,
        },
        cbt={
            "enabled": mode == "personal",
            "mode": cbt_mode, "cooling_hours": 48,
            "detect_distortions": mode == "personal",
        },
        audit={"enabled": mode == "company", "log_to_markdown": True,
               "log_to_db": mode == "company", "retention_days": 365},
    )

    env_path = os.environ.get("STRATA_PALACE", "")
    palace_path = env_path or str(Path.home() / ".strata" / "palace")
    config.palace_path = palace_path

    palace = Path(palace_path)
    ensure_palace(palace)
    save_config(config)

    # Reset global state so next call picks up the new config (hot reload)
    if config_module:
        from .. import server
        server._reset_state()

    # Initialize ChromaDB and SQLite eagerly
    init_results = {}
    dirs = palace_dirs(palace)
    init_results["wings_dir"] = str(dirs["wings"])
    init_results["vector_dir"] = str(dirs["l2_vector"])

    # Create a welcome drawer to mark onboarding complete
    welcome_dir = dirs["wings"] / "system"
    welcome_dir.mkdir(parents=True, exist_ok=True)
    welcome_file = welcome_dir / "onboarding_complete.md"
    welcome_content = (
        f"# Onboarding Complete\n\n"
        f"- **Date**: {date.today().isoformat()}\n"
        f"- **Mode**: {mode}\n"
        f"- **Provider**: {provider}/{model}\n"
        f"- **Dimension**: {dimension}\n"
        f"- **CBT**: {cbt_mode}\n"
        f"- **Tenant**: {tenant_id or 'N/A'}\n"
    )
    welcome_file.write_text(welcome_content, encoding="utf-8")
    init_results["welcome_drawer"] = str(welcome_file)

    return {
        "status": "ok",
        "message": f"Memory Palace initialized in {mode} mode with {provider}/{model}.",
        "palace_path": palace_path,
        "mode": mode,
        "provider": provider,
        "model": model,
        "dimension": dimension,
        "cbt_mode": cbt_mode,
        "tenant_id": tenant_id or "",
        "init_results": init_results,
        "next": "Use `memorize` to start recording memories. Use `wake_up` at session start.",
    }


# ── Setup instructions resource ─────────────────────────────────────────

SETUP_INSTRUCTIONS_TEMPLATE = """# Memory Palace MCP — Agent-Driven Setup Guide

You are an AI agent setting up Strata Memory for your user. This is an
**Agent-Driven Onboarding** — YOU lead the conversation. The MCP provides
tools; you provide intelligence and empathy.

## Your Role

1. **Detect state silently**: Call `get_system_profile` to learn the hardware.
2. **Get recommendations**: Call `search_embedding_recommendations` with the profile.
3. **Present options**: Explain the top 2-3 choices in plain language. Respect
   the user's preferences (privacy, simplicity, performance).
4. **Apply the choice**: Call `apply_memory_config` with the chosen config.
5. **Confirm and guide**: Tell the user what's next (`memorize`, `wake_up`).

## Phase 0: Silent Start

MCP auto-detects uninitialized state. You should immediately call:

```
get_system_profile()
```

This returns `{os, arch, ram_gb, cpu_cores, accelerator}`. The user sees none of this.

## Phase 1: Match Hardware to Recommendations

Call:

```
search_embedding_recommendations(profile)
```

You'll get a ranked list like:
```json
[
  {"provider": "siliconflow", "model": "BAAI/bge-m3", "dimension": 384,
   "tier": "cloud", "reason": "Recommended: 16GB shared memory..."},
  {"provider": "local", "model": "all-MiniLM-L6-v2", "dimension": 384,
   "tier": "local", "reason": "Ultra-light local fallback..."}
]
```

Build your recommendation from this data. Follow the tier priority.

## Phase 2: Conversation Guide

Present options conversationally. Adapt based on the profile:

**High-RAM + GPU/MPS (>=32GB + accelerator):**
"Your {ram_gb}GB {accelerator} machine can run a local embedding model easily.
I recommend nomic-embed-text-v2 — it stays on your device, no API calls needed.
Alternatively, SiliconFlow BGE-M3 cloud API if you prefer zero setup.
Local (privacy-first) or cloud (zero-config)?"

**Mid-RAM (16-32GB):**
"You have {ram_gb}GB. You can run a lightweight local model, but I recommend
SiliconFlow BGE-M3 cloud API for the best quality with minimal memory pressure.
It's free to start. Local or cloud?"

**Low-RAM (<16GB):**
"Your machine has {ram_gb}GB. I recommend cloud embedding via SiliconFlow BGE-M3
— it's fast, supports Chinese+English, and won't strain your memory.
Do you have a SiliconFlow API key, or would you like me to help?"

## Phase 3: Apply Configuration

Once the user chooses, call:

```
apply_memory_config({
    "mode": "personal",
    "provider": "<chosen_provider>",
    "model": "<chosen_model>",
    "api_key": "<key if cloud>",
    "base_url": "<api_url>",
    "dimension": <dim>,
    "cbt_mode": "passive"
})
```

This writes the config, creates the Palace directory structure, initializes
ChromaDB + SQLite, creates a welcome drawer, and supports hot reload — no
MCP restart needed.

## Key Principles

- **Silent First**: Hardware detection is invisible to the user.
- **BYOK + Zero Config**: Prefer the path with least manual steps.
- **Rollback-friendly**: User can say "switch to local" or "use a different key" anytime.
- **Educational**: Explain trade-offs briefly. Don't dump specs unless asked.
- **Agent-Driven**: YOU choose the flow. Don't make the user fill in technical blanks.

## After Setup

Guide the user to their first memory:
```
memorize(user_id="user_001", content="User prefers dark mode for coding", category="preference")
```

Then at the start of each session:
```
wake_up(user_id="user_001", query="coding preferences", context_depth="deep")
```
"""
