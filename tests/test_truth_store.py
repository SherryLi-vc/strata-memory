"""Truth Store integration tests (SQLite SoT)."""

from __future__ import annotations

from pathlib import Path

import pytest

from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def store(tmp_path: Path) -> TruthStore:
    return TruthStore(tmp_path / "truth" / "strata.db")


def test_insert_and_get(store: TruthStore):
    row = store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="s1",
        memory_type="user_preference",
        fact_claim="User prefers Python for backend services.",
        content_hash="abc123",
        confidence=0.9,
        summary="User prefers Python for backend services.",
    )
    assert row["id"]
    got = store.get_by_id(row["id"])
    assert got is not None
    assert got["fact_claim"].startswith("User prefers Python")


def test_dedup_hash_lookup(store: TruthStore):
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="",
        memory_type="factual_truth",
        fact_claim="Deploy target is Kubernetes cluster prod-east.",
        content_hash="hash-dup",
        confidence=0.95,
    )
    found = store.find_by_hash("", "u1", "hash-dup")
    assert found is not None
    assert store.find_by_hash("", "u2", "hash-dup") is None


def test_scratch_promote(store: TruthStore):
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="sess-9",
        memory_type="episodic_event",
        fact_claim="On 2026-08-04 user reviewed the memory architecture.",
        content_hash="h1",
        confidence=0.6,
        is_scratch=True,
    )
    ids = store.promote_scratch("", "u1", "sess-9")
    assert len(ids) == 1
    row = store.get_by_id(ids[0])
    assert row["is_scratch"] == 0
    assert row["layer"] in ("L0", "L2")


def test_fts_search(store: TruthStore):
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="",
        memory_type="user_preference",
        fact_claim="User prefers dark mode Monokai theme in VS Code.",
        content_hash="h-dark",
        confidence=0.9,
        summary="User prefers dark mode Monokai theme in VS Code.",
    )
    hits = store.fts_search("dark Monokai", tenant_id="", user_id="u1", limit=5)
    assert len(hits) >= 1


def test_stats(store: TruthStore):
    store.insert_memory(
        tenant_id="",
        user_id="u1",
        session_id="",
        memory_type="procedure_rule",
        fact_claim="Always run strata_doctor after deployment changes.",
        content_hash="h-proc",
        confidence=0.95,
    )
    st = store.stats()
    assert st["active"] >= 1
    assert "by_layer" in st
