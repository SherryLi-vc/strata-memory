"""Recall says when it cut something: long summaries, the candidate scan limit, the token waterline."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, truth_db_path
from strata_memory.pipeline import recall as recall_mod
from strata_memory.pipeline.recall import TRUNCATION_MARK, recall_context
from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(palace_path=str(palace), mode="personal")
    return cfg, TruthStore(truth_db_path(palace))


def _insert(store, n, text):
    store.insert_memory(
        tenant_id="",
        user_id="u",
        session_id="",
        memory_type="factual_truth",
        fact_claim=text,
        summary="",
        content_hash=f"h{n}",
        confidence=0.9,
        importance=0.5,
    )


def _recall(cfg, store, query="gateway port"):
    return asyncio.run(
        recall_context(config=cfg, store=store, embed_provider=None, chroma=None, user_id="u", query=query)
    )


def test_short_results_are_not_marked(env):
    cfg, store = env
    _insert(store, 1, "The API gateway listens on port 8017.")
    out = _recall(cfg, store)
    assert out["hits"][0]["summary_truncated"] is False
    assert not out["hits"][0]["summary"].endswith(TRUNCATION_MARK)
    assert out["truncated"] is False


def test_long_summary_carries_a_marker(env):
    cfg, store = env
    _insert(store, 1, "The API gateway listens on port 8017. " + "Extra detail about routing. " * 40)
    out = _recall(cfg, store)
    hit = out["hits"][0]
    assert hit["summary_truncated"] is True
    assert hit["summary"].endswith(TRUNCATION_MARK)
    assert out["truncated"] is True
    assert out["truncation"]["summaries_truncated"] == 1


def test_scan_limit_is_reported(env, monkeypatch):
    cfg, store = env
    monkeypatch.setattr(recall_mod, "_CANDIDATE_LIMIT", 3)
    for i in range(5):
        _insert(store, i, f"The API gateway listens on port 80{i:02d} in region {i}.")
    out = _recall(cfg, store)
    assert out["truncated"] is True
    assert out["truncation"]["scan_limit"] == 3
    assert out["truncation"]["scan_limit_reached"] is True


def test_token_waterline_drop_is_reported(env):
    cfg, store = env
    cfg.l0_token_budget = 30
    cfg.l2_token_budget = 0
    for i in range(4):
        _insert(store, i, f"The API gateway listens on port 80{i:02d}; notes about the gateway port setup {i}.")
    out = _recall(cfg, store)
    assert out["truncation"]["token_waterline_dropped"] >= 1
    assert out["truncated"] is True
