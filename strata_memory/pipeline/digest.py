"""Background digest / forgetting job.

Do NOT ask the LLM to decide deletions mid-conversation.
Run as cron / CLI: demote stale L2 → L3, archive expired TTLs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..config import Config
from ..pipeline.scoring import compute_score, promotion_decision
from ..storage.truth_store import TruthStore


def run_digest(
    store: TruthStore,
    config: Config,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply demotion / archive rules to stale memories."""
    now = datetime.now(timezone.utc)
    demoted = 0
    archived = 0
    kept = 0
    actions: list[dict[str, Any]] = []

    candidates = store.candidates_for_digest(
        older_than_days=max(1, config.l3_demotion_days)
    )
    # Full durable scan for TTL + score decisions
    rows = store.iter_for_index(tenant_id=config.tenant_id or "")
    by_id = {r["id"]: r for r in rows}
    for c in candidates:
        by_id[c["id"]] = c

    for row in by_id.values():
        # TTL expiry → archive
        exp = row.get("expires_at")
        if exp:
            try:
                exp_dt = datetime.fromisoformat(exp.replace("Z", "+00:00"))
                if exp_dt.tzinfo is None:
                    exp_dt = exp_dt.replace(tzinfo=timezone.utc)
                if exp_dt < now:
                    actions.append({"id": row["id"], "action": "archive", "reason": "ttl_expired"})
                    if not dry_run:
                        store.archive(row["id"], reason="ttl_expired")
                    archived += 1
                    continue
            except ValueError:
                pass

        last = row.get("last_accessed") or row.get("created_at")
        days = 0
        if last:
            try:
                la = datetime.fromisoformat(last.replace("Z", "+00:00"))
                if la.tzinfo is None:
                    la = la.replace(tzinfo=timezone.utc)
                days = max(0, (now - la).days)
            except ValueError:
                days = 0

        score = compute_score(
            base_importance=float(row.get("importance") or 0.5),
            usage_count=int(row.get("usage_count") or 0),
            emotional_salience=float(row.get("emotional_salience") or 0.0),
            category=_legacy_category(row.get("memory_type", "episodic_event")),
            days_since_last_access=days,
        )
        decision = promotion_decision(
            score=score,
            usage_count=int(row.get("usage_count") or 0),
            is_negative_schema=bool(row.get("is_negative_schema")),
            cooling_hours=config.cbt.cooling_hours,
            created_at=row.get("created_at"),
            days_unaccessed=days,
        )
        act = decision["action"]
        if act == "demote_l3" and row.get("layer") != "L3":
            actions.append({"id": row["id"], "action": "demote_l3", "reason": decision["reason"], "score": score})
            if not dry_run:
                store.demote(row["id"], "L3")
            demoted += 1
        elif act == "delete":
            # Inhibitory control: archive, never hard-delete
            actions.append({"id": row["id"], "action": "archive", "reason": decision["reason"], "score": score})
            if not dry_run:
                store.archive(row["id"], reason="score_below_threshold")
            archived += 1
        else:
            kept += 1

    if not dry_run:
        store.audit(
            "digest_job",
            summary=f"demoted={demoted} archived={archived} kept={kept}",
        )

    return {
        "status": "ok",
        "dry_run": dry_run,
        "demoted": demoted,
        "archived": archived,
        "kept": kept,
        "actions_sample": actions[:30],
    }


def _legacy_category(memory_type: str) -> str:
    return {
        "factual_truth": "fact",
        "user_preference": "preference",
        "procedure_rule": "procedure",
        "episodic_event": "event",
    }.get(memory_type, "event")
