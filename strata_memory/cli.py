"""CLI for Strata Memory.

Usage:
    strata-memory-mcp                         # MCP server
    strata-memory-mcp setup --host cursor
    strata-memory-mcp export --user USER [--out FILE]
    python -m strata_memory.cli init
    python -m strata_memory.cli doctor
    python -m strata_memory.cli stats
    python -m strata_memory.cli digest [--apply]
    python -m strata_memory.cli project
    python -m strata_memory.cli migrate [--apply] [--palace PATH] ...
    python -m strata_memory.cli serve
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import cast


def cmd_init() -> None:
    print("Strata Memory — CLI init")
    print("=" * 40)
    mode = input("Mode [personal/company] (default: personal): ").strip() or "personal"
    tenant_id = ""
    if mode == "company":
        tenant_id = input("tenant_id: ").strip()
    api_key = input("API key (or leave empty and use STRATA_API_KEY): ").strip()
    if api_key:
        os.environ["STRATA_API_KEY"] = api_key

    from . import __version__
    from .config import Config, ensure_palace, save_config, truth_db_path
    from .storage.truth_store import TruthStore

    palace_path = os.environ.get("STRATA_PALACE") or str(Path.home() / ".strata" / "palace")
    cfg = Config(
        mode=mode,
        tenant_id=tenant_id,
        palace_path=palace_path,
        version=__version__,
        embedding={"api_key": api_key or os.environ.get("STRATA_API_KEY", "")},
        cbt={
            "enabled": mode == "personal",
            "mode": "passive" if mode == "personal" else "off",
        },
        audit={"enabled": mode == "company", "log_to_db": True},
    )
    palace = Path(palace_path)
    ensure_palace(palace)
    save_config(cfg)
    TruthStore(truth_db_path(palace))
    print(
        json.dumps(
            {
                "status": "ok",
                "version": __version__,
                "palace": palace_path,
                "truth_db": str(truth_db_path(palace)),
                "mode": mode,
            },
            indent=2,
        )
    )


def cmd_doctor() -> None:
    from .config import load_config, truth_db_path
    from .ops.doctor import strata_doctor
    from .storage.chroma import ChromaStore
    from .storage.truth_store import TruthStore

    cfg = load_config()
    store = TruthStore(truth_db_path(Path(cfg.palace_path)))
    chroma = ChromaStore(Path(cfg.palace_path) / "l2_vector")
    print(json.dumps(strata_doctor(config=cfg, store=store, chroma=chroma), indent=2, ensure_ascii=False))


def cmd_stats() -> None:
    from .config import load_config, truth_db_path
    from .ops.stats import strata_stats
    from .storage.chroma import ChromaStore
    from .storage.truth_store import TruthStore

    cfg = load_config()
    store = TruthStore(truth_db_path(Path(cfg.palace_path)))
    chroma = ChromaStore(Path(cfg.palace_path) / "l2_vector")
    print(json.dumps(strata_stats(config=cfg, store=store, chroma=chroma), indent=2, ensure_ascii=False))


def cmd_digest() -> None:
    from .config import load_config, truth_db_path
    from .pipeline.digest import run_digest
    from .storage.truth_store import TruthStore

    apply = "--apply" in sys.argv
    cfg = load_config()
    store = TruthStore(truth_db_path(Path(cfg.palace_path)))
    print(json.dumps(run_digest(store, cfg, dry_run=not apply), indent=2, ensure_ascii=False))


def cmd_project() -> None:
    from .config import load_config, truth_db_path
    from .ops.projection import dump_markdown_projection
    from .storage.truth_store import TruthStore

    cfg = load_config()
    store = TruthStore(truth_db_path(Path(cfg.palace_path)))
    print(
        json.dumps(
            dump_markdown_projection(store, Path(cfg.palace_path)),
            indent=2,
            ensure_ascii=False,
        )
    )


def cmd_migrate() -> None:
    """Migrate 0.2 Markdown drawers → 2.0 SQLite. Forwards argv to migrate_v02."""
    from .ops.migrate_v02 import main as migrate_main

    # Drop "migrate" so argparse sees only its own flags
    code = migrate_main(sys.argv[2:])
    sys.exit(code)


def cmd_serve() -> None:
    from .server import run

    asyncio.run(run())


def _flag(name: str, default: str = "") -> str:
    if name not in sys.argv:
        return default
    idx = sys.argv.index(name)
    if idx + 1 >= len(sys.argv):
        return default
    return sys.argv[idx + 1]


def cmd_setup() -> None:
    from .ops.setup_host import HostName, render_setup

    host = _flag("--host", "cursor")
    allowed: tuple[HostName, ...] = ("cursor", "claude-code", "claude-desktop")
    if host not in allowed:
        print(
            "Usage: strata-memory-mcp setup --host cursor|claude-code|claude-desktop",
            file=sys.stderr,
        )
        sys.exit(2)
    print(render_setup(cast(HostName, host)), end="")


def cmd_export() -> None:
    from .config import load_config, truth_db_path
    from .pipeline.export_json import export_memories
    from .storage.truth_store import TruthStore

    user_id = _flag("--user")
    if not user_id:
        print(
            "Usage: strata-memory-mcp export --user USER_ID [--out FILE] [--tenant ID] [--session ID]",
            file=sys.stderr,
        )
        sys.exit(2)
    cfg = load_config()
    store = TruthStore(truth_db_path(Path(cfg.palace_path)))
    limit_raw = _flag("--limit", "500")
    payload = export_memories(
        store=store,
        user_id=user_id,
        tenant_id=_flag("--tenant", cfg.tenant_id or ""),
        session_id=_flag("--session", ""),
        include_archived="--include-archived" in sys.argv,
        limit=int(limit_raw or "500"),
    )
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    out = _flag("--out")
    if out:
        Path(out).write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"status": "ok", "path": out, "count": payload.get("count", 0)}))
    else:
        print(text)


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"help", "--help", "-h"}:
        print(
            "Usage: strata-memory-mcp {setup|export|init|doctor|stats|digest|project|migrate|serve}\n"
            "       strata-memory-mcp        # start the MCP server\n"
            "The PyPI name is strata-memory-mcp. Do not run uvx strata-memory."
        )
        sys.exit(0 if len(sys.argv) > 1 else 1)
    cmd = sys.argv[1]
    handlers = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "stats": cmd_stats,
        "digest": cmd_digest,
        "project": cmd_project,
        "migrate": cmd_migrate,
        "serve": cmd_serve,
        "setup": cmd_setup,
        "export": cmd_export,
    }
    if cmd not in handlers:
        print(f"Unknown command: {cmd}")
        print("Usage: strata-memory-mcp {setup|export|init|doctor|stats|digest|project|migrate|serve}")
        sys.exit(1)
    handlers[cmd]()


if __name__ == "__main__":
    main()
