"""Markdown read-only projection from SQLite SoT.

Markdown is no longer the database — it is a human-friendly view
generated on demand (or by nightly dump).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any, Optional

from ..storage.truth_store import TruthStore


def dump_markdown_projection(
    store: TruthStore,
    out_dir: Path,
    *,
    tenant_id: str = "",
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Write read-only Markdown snapshots under out_dir/projection/."""
    out_dir = Path(out_dir)
    proj = out_dir / "projection"
    proj.mkdir(parents=True, exist_ok=True)

    rows = store.iter_for_index(tenant_id=tenant_id, user_id=user_id)
    by_user: dict[str, list[dict]] = {}
    for r in rows:
        by_user.setdefault(r["user_id"], []).append(r)

    files = 0
    for uid, mems in by_user.items():
        user_dir = proj / "users" / uid
        user_dir.mkdir(parents=True, exist_ok=True)

        # L0 profile projection
        l0 = [m for m in mems if m.get("layer") == "L0"]
        if l0:
            lines = [
                "---",
                "strata_projection: true",
                "layer: L0",
                f"user_id: {uid}",
                f"generated: {date.today().isoformat()}",
                "read_only: true",
                "---",
                "",
                f"# Core Profile — {uid}",
                "",
                "> Auto-generated from SQLite Truth Store. Do not treat as SoT.",
                "",
            ]
            for m in l0:
                lines.append(f"- **[{m['memory_type']}]** {m['fact_claim']}  ")
                lines.append(f"  `id={m['id']}` conf={m.get('confidence')}")
            fp = user_dir / "L0_profile.md"
            fp.write_text("\n".join(lines), encoding="utf-8")
            files += 1

        # Per-type dumps
        for mtype in ("factual_truth", "user_preference", "procedure_rule", "episodic_event"):
            subset = [m for m in mems if m.get("memory_type") == mtype]
            if not subset:
                continue
            lines = [
                "---",
                "strata_projection: true",
                f"memory_type: {mtype}",
                f"user_id: {uid}",
                f"generated: {date.today().isoformat()}",
                "read_only: true",
                "---",
                "",
                f"# {mtype} — {uid}",
                "",
            ]
            for m in subset:
                lines.append(f"## {m['id']}")
                lines.append(f"- layer: {m.get('layer')}")
                lines.append(f"- confidence: {m.get('confidence')}")
                lines.append(f"- created: {m.get('created_at')}")
                lines.append("")
                lines.append(m["fact_claim"])
                lines.append("")
            fp = user_dir / f"{mtype}.md"
            fp.write_text("\n".join(lines), encoding="utf-8")
            files += 1

    # Manifest
    manifest = proj / "README.md"
    manifest.write_text(
        f"# Strata Memory Projection\n\n"
        f"Generated: {date.today().isoformat()}\n\n"
        f"These Markdown files are **read-only views** of the SQLite Truth Store.\n"
        f"Edits here are NOT authoritative. Use `commit_memory` MCP tool to write.\n",
        encoding="utf-8",
    )
    files += 1

    return {
        "status": "ok",
        "files_written": files,
        "users": list(by_user.keys()),
        "projection_dir": str(proj),
        "memory_count": len(rows),
    }
