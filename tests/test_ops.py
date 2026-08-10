"""Ops tools: doctor / stats / projection / digest."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.ops.doctor import strata_doctor
from strata_memory.ops.projection import dump_markdown_projection
from strata_memory.ops.stats import strata_stats
from strata_memory.pipeline.digest import run_digest
from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(palace_path=str(palace), version="2.0.0", mode="personal")
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="",
        memory_type="factual_truth",
        fact_claim="SQLite is the single source of truth for Strata Memory 2.0.",
        content_hash="h-sot",
        confidence=0.99,
        summary="SQLite is the single source of truth for Strata Memory 2.0.",
    )
    return cfg, store, palace


def test_doctor(env):
    cfg, store, _ = env
    report = strata_doctor(config=cfg, store=store, chroma=None)
    assert report["status"] in ("ok", "degraded")
    assert "checks" in report


def test_stats_waterlines(env):
    cfg, store, _ = env
    st = strata_stats(config=cfg, store=store, chroma=None)
    assert st["status"] == "ok"
    assert "waterlines" in st
    assert "L0" in st["waterlines"]


def test_projection(env):
    cfg, store, palace = env
    out = dump_markdown_projection(store, palace, user_id="u1")
    assert out["files_written"] >= 1
    assert (palace / "projection" / "README.md").exists()


def test_digest_dry_run(env):
    cfg, store, _ = env
    result = run_digest(store, cfg, dry_run=True)
    assert result["status"] == "ok"
    assert result["dry_run"] is True
