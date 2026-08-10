"""Multi-signal ranking on top of Hybrid RRF (Memory 3.0 Slice C).

final ≈ recency × relevance × importance × (1 + usage_boost) × freshness

All components normalized to ~[0, 1] for explainability.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any, Optional


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return None


def _days_since(iso: Optional[str], now: datetime) -> float:
    dt = _parse_dt(iso)
    if not dt:
        return 30.0
    return max(0.0, (now - dt).total_seconds() / 86400.0)


def multi_signal_score(
    row: dict[str, Any],
    *,
    rrf_score: float,
    max_rrf: float = 1.0,
    now: Optional[datetime] = None,
    half_life_days: float = 30.0,
) -> tuple[float, dict[str, float]]:
    """Return (final_score, breakdown)."""
    now = now or datetime.now(timezone.utc)

    # Relevance from RRF (normalize by batch max)
    denom = max(max_rrf, 1e-9)
    relevance = max(0.0, min(1.0, float(rrf_score) / denom))

    # Recency: exponential decay on last_accessed or created_at
    anchor = row.get("last_accessed") or row.get("created_at")
    days = _days_since(anchor, now)
    recency = math.exp(-math.log(2) * days / max(half_life_days, 1.0))

    importance = max(0.05, min(1.0, float(row.get("importance") or 0.5)))

    usage = int(row.get("usage_count") or 0)
    usage_boost = min(1.0, math.log2(1.0 + usage) / 5.0)  # ~1.0 at usage≈31

    # Freshness: 1.0 if no TTL; else remaining life fraction
    freshness = 1.0
    exp = _parse_dt(row.get("expires_at"))
    if exp is not None:
        created = _parse_dt(row.get("created_at")) or now
        total = max(1.0, (exp - created).total_seconds())
        remaining = max(0.0, (exp - now).total_seconds())
        freshness = max(0.05, min(1.0, remaining / total))

    final = recency * relevance * importance * (1.0 + 0.3 * usage_boost) * freshness

    breakdown = {
        "recency": round(recency, 4),
        "relevance": round(relevance, 4),
        "importance": round(importance, 4),
        "usage_boost": round(usage_boost, 4),
        "freshness": round(freshness, 4),
        "rrf_raw": round(float(rrf_score), 4),
        "final": round(final, 4),
    }
    return final, breakdown
