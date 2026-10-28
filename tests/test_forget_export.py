"""Forget stays inside tenant/user/session scope and does not survive a rebuild."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.governance import ToolError
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.export_json import EXPORT_FORMAT, export_memories
from strata_memory.pipeline.forget import forget_memories
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.chroma import ChromaStore
from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.0",
        cbt={"enabled": True, "mode": "passive", "cooling_hours": 48, "detect_distortions": True},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    chroma = ChromaStore(palace / "l2_vector")
    return cfg, store, chroma


def _commit(cfg, store, **kwargs):
    async def run():
        return await commit_memory(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            confidence_score=0.95,
            **kwargs,
        )

    return asyncio.run(run())


def test_forget_by_id_is_gone_from_store_and_index(env):
    cfg, store, chroma = env
    kept = _commit(
        cfg,
        store,
        user_id="user_a",
        memory_type="factual_truth",
        fact_claim="The API gateway listens on port 8017 in production.",
    )
    doomed = _commit(
        cfg,
        store,
        user_id="user_a",
        memory_type="user_preference",
        fact_claim="User prefers the Monokai Pro theme with dark mode.",
    )
    chroma.add(
        documents=["doomed"],
        metadatas=[{"user_id": "user_a", "tenant_id": ""}],
        ids=[doomed["memory_id"]],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
    )

    result = forget_memories(
        store=store,
        chroma=chroma,
        user_id="user_a",
        memory_id=doomed["memory_id"],
    )
    assert result["status"] == "ok"
    assert result["deleted_count"] == 1
    assert store.get_by_id(doomed["memory_id"]) is None
    assert store.get_by_id(kept["memory_id"]) is not None
    remaining = {row["id"] for row in store.iter_for_index(user_id="user_a")}
    assert doomed["memory_id"] not in remaining
    assert kept["memory_id"] in remaining
    assert store.fts_search("Monokai", user_id="user_a") == []
    assert chroma.count() == 0

    async def recall():
        return await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_a",
            query="Monokai Pro theme dark mode",
            limit=5,
        )

    recalled = asyncio.run(recall())
    assert all(hit["id"] != doomed["memory_id"] for hit in recalled["hits"])


def test_forget_respects_user_tenant_and_session(env):
    cfg, store, chroma = env
    owned = _commit(
        cfg,
        store,
        user_id="user_a",
        tenant_id="acme",
        session_id="sess_a",
        memory_type="factual_truth",
        fact_claim="Tenant acme keeps the warehouse code WH-19 on site.",
    )
    other_user = _commit(
        cfg,
        store,
        user_id="user_b",
        tenant_id="acme",
        memory_type="factual_truth",
        fact_claim="Tenant acme keeps the warehouse code WH-19 on site for Bob.",
    )
    other_session = _commit(
        cfg,
        store,
        user_id="user_a",
        tenant_id="acme",
        session_id="sess_b",
        memory_type="episodic_event",
        fact_claim="On 2026-08-10 sess_b recorded a warehouse walkthrough WH-19.",
    )

    with pytest.raises(ToolError) as scoped:
        forget_memories(store=store, chroma=chroma, user_id="user_b", memory_id=owned["memory_id"], tenant_id="acme")
    assert scoped.value.code == "SCOPE_VIOLATION"
    assert store.get_by_id(owned["memory_id"]) is not None

    preview = forget_memories(
        store=store,
        chroma=chroma,
        user_id="user_a",
        tenant_id="acme",
        session_id="sess_a",
        confirm=False,
    )
    assert preview["error_code"] == "CONFIRMATION_REQUIRED"
    assert store.get_by_id(owned["memory_id"]) is not None

    deleted = forget_memories(
        store=store,
        chroma=chroma,
        user_id="user_a",
        tenant_id="acme",
        session_id="sess_a",
        confirm=True,
    )
    assert deleted["deleted_count"] == 1
    assert store.get_by_id(owned["memory_id"]) is None
    assert store.get_by_id(other_user["memory_id"]) is not None
    assert store.get_by_id(other_session["memory_id"]) is not None


def test_export_is_scoped_json(env):
    cfg, store, _chroma = env
    _commit(
        cfg,
        store,
        user_id="user_a",
        memory_type="factual_truth",
        fact_claim="User A stores the gateway port 8017 locally.",
    )
    _commit(
        cfg,
        store,
        user_id="user_b",
        memory_type="factual_truth",
        fact_claim="User B stores a different gateway port 9090 locally.",
    )
    exported = export_memories(store=store, user_id="user_a")
    assert exported["status"] == "ok"
    assert exported["format"] == EXPORT_FORMAT
    assert exported["count"] == 1
    assert exported["memories"][0]["user_id"] == "user_a"
    assert "8017" in exported["memories"][0]["fact_claim"]
    assert "9090" not in json.dumps(exported)

    other_tenant = export_memories(store=store, user_id="user_a", tenant_id="elsewhere")
    assert other_tenant["count"] == 0


def test_export_cli_writes_file(env, tmp_path: Path, monkeypatch):
    cfg, store, _chroma = env
    _commit(
        cfg,
        store,
        user_id="user_a",
        memory_type="decision_record",
        fact_claim="On 2026-08-10 the team decided SQLite is the memory source of truth.",
    )
    monkeypatch.setenv("STRATA_PALACE", cfg.palace_path)
    out = tmp_path / "memories.json"
    monkeypatch.setattr(sys, "argv", ["strata-memory", "export", "--user", "user_a", "--out", str(out)])
    from strata_memory.cli import main

    main()
    body = out.read_text(encoding="utf-8")
    assert "strata-memory-export-v1" in body
    assert "SQLite is the memory source of truth" in body
    assert "user_a" in body
