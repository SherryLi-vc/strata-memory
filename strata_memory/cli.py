"""Optional CLI entry point for Strata Memory.

Usage:
    python -m strata_memory.cli init    # Interactive init wizard (fallback)
    python -m strata_memory.cli health  # Print system health
    python -m strata_memory.cli serve   # Start MCP server (same as __main__)

For Agent-Driven onboarding, use the MCP tools via your Agent:
    get_system_profile()
    search_embedding_recommendations()
    apply_memory_config()
"""

from __future__ import annotations

import json
import sys


def cmd_init() -> None:
    """Minimal CLI init — the Agent-Driven path is preferred."""
    print("Strata Memory — CLI Setup (fallback)")
    print("=" * 40)
    print()
    print("For the best experience, let your AI Agent handle setup via MCP tools:")
    print("  get_system_profile()")
    print("  search_embedding_recommendations()")
    print("  apply_memory_config(...)")
    print()
    print("Or use this CLI fallback:")
    print()
    mode = input("Mode [personal/company] (default: personal): ").strip() or "personal"
    provider = input("Embedding provider (default: siliconflow): ").strip() or "siliconflow"
    model = input("Model (default: BAAI/bge-m3): ").strip() or "BAAI/bge-m3"
    api_key = input("API key: ").strip()

    from .tools.system_profile import apply_memory_config
    result = apply_memory_config({
        "mode": mode,
        "provider": provider,
        "model": model,
        "api_key": api_key,
    })
    print()
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_health() -> None:
    """Print system health from config."""
    from .config import is_initialized, load_config
    from .tools.system_profile import get_system_profile

    print("=== System Profile ===")
    print(json.dumps(get_system_profile(), indent=2))
    print()
    if is_initialized():
        cfg = load_config()
        print("=== Strata Config ===")
        print(f"  Mode:     {cfg.mode}")
        print(f"  Palace:   {cfg.palace_path}")
        print(f"  Provider: {cfg.embedding.provider}/{cfg.embedding.model}")
        print(f"  CBT:      {cfg.cbt.mode}")
        print(f"  Audit:    {'enabled' if cfg.audit.enabled else 'markdown-only'}")
    else:
        print("Strata Memory not initialized. Run `python -m strata_memory.cli init`.")


def cmd_serve() -> None:
    """Start the MCP server."""
    import asyncio
    from .server import run
    asyncio.run(run())


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m strata_memory.cli {init|health|serve}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "init":
        cmd_init()
    elif cmd == "health":
        cmd_health()
    elif cmd == "serve":
        cmd_serve()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python -m strata_memory.cli {init|health|serve}")
        sys.exit(1)


if __name__ == "__main__":
    main()
