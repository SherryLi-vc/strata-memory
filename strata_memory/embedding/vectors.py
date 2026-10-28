"""Fit provider vectors to the configured storage dimension."""

from __future__ import annotations


def fit_vector(
    vec: list[float],
    *,
    dimension: int,
    truncate: bool,
    model: str,
    base_url: str,
) -> list[float]:
    """Return ``vec`` at ``dimension``.

    Matryoshka models (BAAI/bge-m3 on SiliconFlow) may be truncated.
    Other models must match ``dimension`` exactly so the index stays consistent.
    """
    if len(vec) == dimension:
        return vec
    if len(vec) > dimension and truncate:
        return vec[:dimension]
    where = f"model {model}"
    if base_url:
        where += f" at {base_url}"
    raise RuntimeError(
        f"Embedding length {len(vec)} != configured dimension {dimension} ({where}). "
        "Set STRATA_EMBEDDING_DIMENSION to the model's native size and rebuild the index "
        "with strata_rebuild_index(confirm=true). "
        "BAAI/bge-m3 on SiliconFlow is truncated to the configured dimension by default. "
        "Set STRATA_EMBEDDING_TRUNCATE=1 to force truncation, or =0 to disable it."
    )
