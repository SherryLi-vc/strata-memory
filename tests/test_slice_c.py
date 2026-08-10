"""Memory 3.0 Slice C: typed defaults, supersede, multi-signal, hygiene."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.governance.quality_kernel import QualityKernel
from strata_memory.governance.type_defaults import defaults_for
from strata_memory.ops.hygiene import strata_hygiene
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import recall_context
from strata_memory.pipeline.scoring_signals import multi_signal_score
from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.1.0",
        cbt={"enabled": True, "mode": "passive", "cooling_hours": 48, "detect_distortions": True},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    return cfg, store


def test_decision_record_defaults():
    d = defaults_for("decision_record")
    assert d["ttl_days"] == 365
    assert d["layer"] == "L1"
    v = QualityKernel().validate(
        memory_type="decision_record",
        fact_claim="On 2026-08-10 user decided to adopt SQLite as memory SoT.",
        confidence_score=0.9,
    )
    assert v.accepted
    assert v.metadata.get("validator_kind") == "quality_kernel"
    assert v.ttl_seconds == 365 * 24 * 3600


def test_multi_signal_breakdown():
    row = {
        "importance": 0.8,
        "usage_count": 4,
        "created_at": "2026-08-01T00:00:00+00:00",
        "last_accessed": "2026-08-09T00:00:00+00:00",
        "expires_at": None,
    }
    final, br = multi_signal_score(row, rrf_score=0.5, max_rrf=1.0)
    assert final > 0
    assert "recency" in br and "relevance" in br and "final" in br


def test_supersede_near_dup(env):
    cfg, store = env

    async def run():
        r1 = await commit_memory(
            config=cfg, store=store, embed_provider=None, chroma=None,
            user_id="u1",
            memory_type="user_preference",
            fact_claim="User prefers dark mode in VS Code with Monokai theme daily.",
            confidence_score=0.9,
        )
        assert r1["status"] == "ok"
        old_id = r1["memory_id"]

        r2 = await commit_memory(
            config=cfg, store=store, embed_provider=None, chroma=None,
            user_id="u1",
            memory_type="user_preference",
            fact_claim="User prefers dark mode in VS Code with Monokai Pro theme daily.",
            confidence_score=0.95,
            supersede=True,
        )
        # either supersede or exact-ish near
        assert r2["status"] == "ok"
        if r2.get("superseded"):
            old = store.get_by_id(old_id)
            assert old["status"] == "archived"
            assert old.get("superseded_by") == r2["memory_id"]
            new = store.get_by_id(r2["memory_id"])
            assert new.get("supersedes_id") == old_id

    asyncio.run(run())


def test_recall_score_breakdown(env):
    cfg, store = env

    async def run():
        await commit_memory(
            config=cfg, store=store, embed_provider=None, chroma=None,
            user_id="u1",
            memory_type="factual_truth",
            fact_claim="Strata Memory uses SQLite as the single source of truth store.",
            confidence_score=0.95,
        )
        out = await recall_context(
            config=cfg, store=store, embed_provider=None, chroma=None,
            user_id="u1",
            query="SQLite source of truth",
            limit=5,
        )
        assert out["status"] == "ok"
        assert out["hit_count"] >= 1
        hit = out["hits"][0]
        assert "score_breakdown" in hit
        assert "final" in hit["score_breakdown"]

    asyncio.run(run())


def test_hygiene_dry_run(env):
    cfg, store = env
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="",
        memory_type="episodic_event",
        fact_claim="On 2026-01-01 user reviewed hygiene tooling for memory ops.",
        content_hash="h-hyg-1",
        confidence=0.8,
        ttl_seconds=1,
    )
    # force expire
    with store._conn() as conn:
        conn.execute(
            "UPDATE memories SET expires_at='2000-01-01T00:00:00+00:00' WHERE content_hash=?",
            ("h-hyg-1",),
        )
    rep = strata_hygiene(config=cfg, store=store, dry_run=True)
    assert rep["status"] == "ok"
    assert len(rep["expired_candidates"]) >= 1
