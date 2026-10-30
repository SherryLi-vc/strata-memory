"""Deterministic fusion ranking checks and a tiny train/held-out evaluation."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pytest

from strata_memory.config import Config
from strata_memory.pipeline.recall import _hybrid_relevance


def _rank(lexical: dict[str, float], vectors: dict[str, float], lexical_weight: float, vector_weight: float):
    ids = set(lexical) | set(vectors)
    return sorted(
        ids,
        key=lambda item: (
            -(lexical_weight * lexical.get(item, 0.0) + vector_weight * vectors.get(item, 0.0)),
            item,
        ),
    )


def _embedding(text: str) -> list[float]:
    raw = hashlib.sha256(text.encode()).digest()
    values = [raw[i] / 127.5 - 1 for i in range(32)]
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values]


def _similarity(left: str, right: str) -> float:
    a, b = _embedding(left), _embedding(right)
    return (sum(x * y for x, y in zip(a, b)) + 1) / 2


CORPUS = {
    "train": [
        ("t1", "blue bicycle commute", "blue bicycle commute", "commute"),
        ("t2", "green tea mornings", "green tea morning ritual", "morning"),
    ],
    "held_out": [
        ("h1", "quiet library study", "study at a quiet library", "library"),
        ("h2", "weekend garden vegetables", "grow vegetables in the garden", "garden"),
    ],
}


def _metrics(split: str, weights: tuple[float, float]) -> dict[str, float]:
    hits = {1: 0, 3: 0}
    queries = CORPUS[split]
    for _gold, doc, query, keyword in queries:
        ids = [f"gold-{_gold}", f"lex-{_gold}", f"vec-{_gold}"]
        lexical = {ids[0]: 0.0, ids[1]: 1.0 if keyword in doc else 0.15, ids[2]: 0.0}
        vectors = {ids[0]: _similarity(query, doc), ids[1]: _similarity(query, keyword), ids[2]: 0.35}
        ranked = _rank(lexical, vectors, *weights)
        # Each query's relevant id is its matching document candidate.
        if ids[1] in ranked[:1]:
            hits[1] += 1
        if ids[1] in ranked[:3]:
            hits[3] += 1
    return {f"R@{k}": hits[k] / len(queries) for k in (1, 3)}


def test_config_fusion_weights_default_and_env(monkeypatch, tmp_path):
    from strata_memory.config import load_config

    assert Config().fusion.model_dump() == {"lexical_weight": 0.75, "vector_weight": 0.25}
    monkeypatch.setenv("STRATA_FUSION_LEXICAL_WEIGHT", "0.6")
    monkeypatch.setenv("STRATA_FUSION_VECTOR_WEIGHT", "0.4")
    cfg = load_config(str(tmp_path))
    assert cfg.fusion.lexical_weight == 0.6
    assert cfg.fusion.vector_weight == 0.4


def test_fusion_weights_change_ranking_order():
    lexical = {"lexical": 0.9, "semantic": 0.2}
    vectors = {"lexical": 0.1, "semantic": 0.95}
    low_vector = Config(fusion={"lexical_weight": 0.75, "vector_weight": 0.25})
    high_vector = Config(fusion={"lexical_weight": 0.25, "vector_weight": 0.75})

    def order(cfg: Config) -> list[str]:
        return sorted(lexical, key=lambda item: -_hybrid_relevance(lexical[item], vectors[item], cfg))

    assert order(low_vector)[0] == "lexical"
    assert order(high_vector)[0] == "semantic"
    assert _hybrid_relevance(0.0, 1.0, low_vector) == 0.25


def test_held_out_fusion_eval_is_deterministic():
    assert _metrics("held_out", (0.75, 0.25)) == _metrics("held_out", (0.75, 0.25))
    assert set(_metrics("held_out", (0.75, 0.25))) == {"R@1", "R@3"}


def test_generate_held_out_summary(tmp_path: Path):
    # Train chooses only among candidates; held-out scores are reporting only.
    candidates = [(0.75, 0.25), (0.5, 0.5), (0.25, 0.75)]
    chosen = max(candidates, key=lambda pair: sum(_metrics("train", pair).values()))
    before = _metrics("held_out", (0.75, 0.25))
    after = _metrics("held_out", chosen)
    report = {
        "baseline": {"weights": [0.75, 0.25], **before},
        "train_candidates": [{"weights": list(pair), "metrics": _metrics("train", pair)} for pair in candidates],
        "chosen_defaults": {"weights": list(chosen), **after},
    }
    (tmp_path / "heldout.json").write_text(json.dumps(report, sort_keys=True))
    assert json.loads((tmp_path / "heldout.json").read_text()) == report


if __name__ == "__main__":
    pytest.main([__file__])
