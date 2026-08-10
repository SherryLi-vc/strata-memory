"""strata_hygiene — non-destructive repair & reports (Slice C).

Actions (default dry_run=true):
  - list / archive TTL-expired active rows
  - report content_hash duplicates
  - scan for secret-like residual in active claims
  - rebuild FTS from content table (optional apply)
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Optional

from ..config import Config
from ..governance.quality_kernel import SECRET_PATTERNS
from ..storage.truth_store import TruthStore


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def strata_hygiene(
    *,
    config: Config,
    store: TruthStore,
    dry_run: bool = True,
    rebuild_fts: bool = False,
    archive_expired: bool = True,
    tenant_id: str = "",
    user_id: str = "",
) -> dict[str, Any]:
    tenant_id = tenant_id or config.tenant_id or ""
    report: dict[str, Any] = {
        "status": "ok",
        "dry_run": dry_run,
        "expired_candidates": [],
        "expired_archived": 0,
        "hash_duplicates": [],
        "secret_hits": [],
        "fts_rebuild": None,
    }

    # ── TTL expired ──
    if archive_expired:
        expired = store.list_expired(tenant_id=tenant_id, user_id=user_id or None, limit=200)
        report["expired_candidates"] = [
            {"id": r["id"], "expires_at": r.get("expires_at"), "memory_type": r["memory_type"]}
            for r in expired[:50]
        ]
        if not dry_run:
            n = 0
            for r in expired:
                if store.archive(r["id"], reason="ttl_expired_hygiene"):
                    n += 1
            report["expired_archived"] = n
            store.audit(
                "strata_hygiene_archive",
                tenant_id=tenant_id,
                user_id=user_id,
                summary=f"archived_expired={n}",
            )

    # ── Hash duplicates ──
    dups = store.find_hash_duplicates(tenant_id=tenant_id, user_id=user_id or None)
    report["hash_duplicates"] = dups[:30]
    report["hash_duplicate_groups"] = len(dups)

    # ── Secret residual scan ──
    rows = store.iter_for_index(tenant_id=tenant_id, user_id=user_id or None)
    secret_hits = []
    for r in rows[:2000]:
        text = r.get("fact_claim") or ""
        for pat in SECRET_PATTERNS:
            if pat.search(text):
                secret_hits.append({
                    "id": r["id"],
                    "memory_type": r["memory_type"],
                    "preview": text[:80],
                })
                break
    report["secret_hits"] = secret_hits[:20]
    report["secret_hit_count"] = len(secret_hits)

    # ── FTS rebuild ──
    if rebuild_fts:
        if dry_run:
            report["fts_rebuild"] = {"status": "skipped", "reason": "dry_run"}
        else:
            report["fts_rebuild"] = store.rebuild_fts()
            store.audit("strata_hygiene_fts", summary=str(report["fts_rebuild"]))

    issues = []
    if report["hash_duplicate_groups"]:
        issues.append(f"{report['hash_duplicate_groups']} hash-duplicate groups")
    if report["secret_hit_count"]:
        issues.append(f"{report['secret_hit_count']} secret-like residuals")
    if report["expired_candidates"] and dry_run:
        issues.append(f"{len(report['expired_candidates'])}+ expired candidates (dry_run)")

    report["message"] = (
        "Hygiene clean." if not issues
        else "Hygiene findings: " + "; ".join(issues)
        + (". Re-run with dry_run=false to archive expired." if dry_run and report["expired_candidates"] else "")
    )
    report["recommendation"] = (
        "All clear." if not issues
        else "Review secret_hits manually; archive expired with dry_run=false; "
             "resolve hash dups via supersede commits."
    )
    return report
