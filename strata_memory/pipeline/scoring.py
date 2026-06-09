"""Memory scoring engine — psych-validated formula.

Implements the optimized scoring formula from the cognitive psychology review:

  final_score = base_importance
              × (1 + log₂(1 + usage_count))
              × e^emotional_salience
              × decay_rate^days

Category-specific decay rates (from Ebbinghaus / Murre & Dros):
  event          0.85  — episodic fades fastest
  lesson         0.90
  preference     0.95
  procedure      0.98  — procedural knowledge very stable
  core_identity  1.00  — Anchor Exemption, no decay

Promotion gating (enhanced):
  L2 → L0:  final_score > 0.8 AND usage_count ≥ 5 AND cooling passed
                                     AND is_negative_schema = false
  L2 → L2:  final_score 0.4~0.8  (keep)
  L2 → L3:  final_score < 0.3 OR 30 days unaccessed
  L3 → del: final_score < 0.1

Cooling-off buffer: 48h delay before any promotion decision
(Prevents single-event overlearning / "flashbulb" false consolidation)
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta


def compute_score(
    base_importance: float,
    usage_count: int,
    emotional_salience: float,
    category: str,
    days_since_last_access: int,
    decay_rates: dict[str, float] | None = None,
) -> float:
    """Compute the psych-validated memory strength score.

    Args:
        base_importance:      LLM-assessed core importance (0.0–1.0)
        usage_count:          Times retrieved/referenced
        emotional_salience:   Emotional arousal (0.0–1.0)
        category:             Memory category (event|preference|procedure|...)
        days_since_last_access: Days since last retrieval
        decay_rates:          Optional override for category decay rates

    Returns:
        final_score: 0.0–~2.7 range (can exceed 1.0 for high-usage + high-salience)
    """
    if decay_rates is None:
        from ..config import decay_rate_for as drf
        decay_rate = drf(category)
    else:
        decay_rate = decay_rates.get(category, 0.93)

    # Usage: logarithmic (marginal returns diminish — testing effect)
    usage_factor = 1.0 + math.log2(1.0 + usage_count) * 0.3

    # Emotional salience: exponential (e^salience ∈ [1, 2.718])
    salience_factor = math.exp(emotional_salience)

    # Time decay: exponential (Ebbinghaus)
    decay_factor = decay_rate ** days_since_last_access

    score = base_importance * usage_factor * salience_factor * decay_factor
    return round(score, 4)


def promotion_decision(
    score: float,
    usage_count: int,
    is_negative_schema: bool,
    cooling_hours: int,
    created_at: str | None,
    days_unaccessed: int = 0,
) -> dict:
    """Decide whether a memory should be promoted, kept, or demoted.

    Returns a dict with:
      action:   "promote_l0" | "keep_l2" | "demote_l3" | "delete"
      reason:   Human-readable explanation
    """
    now = datetime.now()

    # Cooling-off check
    if created_at:
        try:
            created = datetime.fromisoformat(created_at)
            hours_since = (now - created).total_seconds() / 3600
            cooling_passed = hours_since >= cooling_hours
        except (ValueError, TypeError):
            cooling_passed = True
    else:
        cooling_passed = True

    # L0 promotion requires: high score, sufficient usage, cooling passed, not negative schema
    if score > 0.8 and usage_count >= 5:
        if is_negative_schema:
            return {"action": "keep_l2", "reason": "Negative schema blocked from L0 promotion"}
        if not cooling_passed:
            remaining = cooling_hours - int((now - datetime.fromisoformat(created_at)).total_seconds() / 3600)
            return {"action": "keep_l2", "reason": f"Cooling-off: {remaining}h remaining before promotion"}
        return {"action": "promote_l0", "reason": "High score + usage + cooling passed"}

    # Demotion: low score or long unaccessed
    if score < 0.3 or days_unaccessed > 30:
        if score < 0.1:
            return {"action": "delete", "reason": "Score below deletion threshold"}
        return {"action": "demote_l3", "reason": "Low score or 30+ days unaccessed — compress to cold storage"}

    return {"action": "keep_l2", "reason": "Stable L2 memory"}


def needs_decontextualization(category: str) -> bool:
    """Check whether this memory type requires decontextualization for L0."""
    return category in ("event", "lesson", "fact")


def estimate_emotional_salience(text: str) -> float:
    """Keyword-based fast screening for emotional salience (V2: LLM-powered).

    Returns a float 0.0–1.0 indicating emotional intensity.
    """
    high_emotion_words = [
        "崩溃", "绝望", "兴奋", "狂喜", "愤怒", "恐惧", "震惊",
        "amazing", "terrible", "devastat", "thrilled", "furious",
        "全搞砸了", "彻底完了", "太棒了", "激动",
    ]
    medium_emotion_words = [
        "开心", "难过", "焦虑", "担心", "满意", "失望", "紧张",
        "happy", "sad", "worried", "anxious", "excited",
    ]

    text_lower = text.lower()
    high_count = sum(1 for w in high_emotion_words if w in text_lower)
    med_count = sum(1 for w in medium_emotion_words if w in text_lower)

    salience = min(1.0, high_count * 0.35 + med_count * 0.15)
    return round(salience, 2)
