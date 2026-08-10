"""CLI for Strata Memory 2.0.

Usage:
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


def cmd_init() -> None:
    print("Strata Memory 2.0 — CLI init")
    print("=" * 40)
    mode = input("Mode [personal/company] (default: personal): ").strip() or "personal"
    tenant_id = ""
    if mode == "company":
        tenant_id = input("tenant_id: ").strip()
    api_key = input("API key (or leave empty and use STRATA_API_KEY): ").strip()
    if api_key:
        os.environ["STRATA_API_KEY"] = api_key

    from .config import Config, ensure_palace, save_config, truth_db_path
    from .storage.truth_store import TruthStore

    palace_path = os.environ.get("STRATA_PALACE") or str(Path.home() / ".strata" / "palace")
    cfg = Config(
        mode=mode,
        tenant_id=tenant_id,
        palace_path=palace_path,
        version="2.0.0",
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
    print(json.dumps({
        "status": "ok",
        "version": "2.0.0",
        "palace": palace_path,
        "truth_db": str(truth_db_path(palace)),
        "mode": mode,
    }, indent=2))


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
    print(json.dumps(
        dump_markdown_projection(store, Path(cfg.palace_path)),
        indent=2,
        ensure_ascii=False,
    ))


def cmd_migrate() -> None:
    """Migrate 0.2 Markdown drawers → 2.0 SQLite. Forwards argv to migrate_v02."""
    from .ops.migrate_v02 import main as migrate_main

    # Drop "migrate" so argparse sees only its own flags
    code = migrate_main(sys.argv[2:])
    sys.exit(code)


def cmd_serve() -> None:
    from .server import run
    asyncio.run(run())


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m strata_memory.cli "
            "{init|doctor|stats|digest|project|migrate|serve}"
        )
        sys.exit(1)
    cmd = sys.argv[1]
    handlers = {
        "init": cmd_init,
        "doctor": cmd_doctor,
        "stats": cmd_stats,
        "digest": cmd_digest,
        "project": cmd_project,
        "migrate": cmd_migrate,
        "serve": cmd_serve,
    }
    if cmd not in handlers:
        print(f"Unknown command: {cmd}")
        print(
            "Usage: python -m strata_memory.cli "
            "{init|doctor|stats|digest|project|migrate|serve}"
        )
        sys.exit(1)
    handlers[cmd]()


if __name__ == "__main__":
    main()
