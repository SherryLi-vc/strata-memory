"""strata_stats — L0–L3 token waterline & trajectory summary."""

from __future__ import annotations

from typing import Any, Optional

from ..config import Config
from ..storage.chroma import ChromaStore
from ..storage.truth_store import TruthStore


def strata_stats(
    *,
    config: Config,
    store: TruthStore,
    chroma: Optional[ChromaStore] = None,
    user_id: str = "",
) -> dict[str, Any]:
    st = store.stats()
    by_layer = st.get("by_layer") or {}

    # Rough token budgets vs load
    # Assume avg 80 tokens per active memory summary for waterline estimate
    def layer_tokens(layer: str) -> int:
        n = by_layer.get(layer, 0)
        return n * 80

    waterlines = {
        "L0": {
            "count": by_layer.get("L0", 0),
            "tokens_approx": layer_tokens("L0"),
            "budget": config.l0_token_budget,
            "utilization": round(layer_tokens("L0") / max(1, config.l0_token_budget), 3),
        },
        "L1": {
            "count": by_layer.get("L1", 0),
            "tokens_approx": layer_tokens("L1"),
            "budget": config.l1_token_budget,
            "utilization": round(layer_tokens("L1") / max(1, config.l1_token_budget), 3),
        },
        "L2": {
            "count": by_layer.get("L2", 0),
            "tokens_approx": layer_tokens("L2"),
            "budget": config.l2_token_budget,
            "utilization": round(layer_tokens("L2") / max(1, config.l2_token_budget), 3),
        },
        "L3": {
            "count": by_layer.get("L3", 0),
            "tokens_approx": layer_tokens("L3"),
            "budget": None,
            "utilization": None,
        },
        "scratch": {
            "count": by_layer.get("scratch", 0) or st.get("scratch", 0),
            "tokens_approx": (by_layer.get("scratch", 0) or st.get("scratch", 0)) * 60,
            "budget": 1500,
            "utilization": None,
        },
    }

    alerts = []
    for layer, w in waterlines.items():
        util = w.get("utilization")
        if util is not None and util > 0.85:
            alerts.append({
                "layer": layer,
                "severity": "high",
                "message": f"{layer} utilization {util:.0%} — risk of context overflow on deep recall.",
            })
        elif util is not None and util > 0.6:
            alerts.append({
                "layer": layer,
                "severity": "medium",
                "message": f"{layer} utilization {util:.0%}.",
            })

    traj = store.trajectory_summary(limit=30)
    vc = 0
    if chroma is not None:
        try:
            vc = chroma.count()
        except Exception:
            vc = -1

    user_slice = None
    if user_id:
        user_layers = store.count_by_layer(
            tenant_id=config.tenant_id or "", user_id=user_id
        )
        user_slice = {"user_id": user_id, "by_layer": user_layers}

    return {
        "status": "ok",
        "version": config.version,
        "mode": config.mode,
        "palace": config.palace_path,
        "truth_store": st,
        "vector_count": vc,
        "waterlines": waterlines,
        "alerts": alerts,
        "trajectory_by_tool": traj,
        "user_slice": user_slice,
        "budgets": {
            "l0_token_budget": config.l0_token_budget,
            "l1_token_budget": config.l1_token_budget,
            "l2_token_budget": config.l2_token_budget,
            "l1_days": config.l1_days,
            "l2_top_k": config.l2_top_k,
        },
    }
