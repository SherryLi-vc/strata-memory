"""End-to-end commit → recall → expand without external embedding API."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import expand_memory_detail, recall_context
from strata_memory.storage.truth_store import TruthStore


@pytest.fixture
def env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.0.0",
        cbt={"enabled": True, "mode": "passive", "cooling_hours": 48, "detect_distortions": True},
        embedding={"provider": "siliconflow", "model": "BAAI/bge-m3", "api_key": "", "dimension": 384},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    return cfg, store


def test_commit_and_recall_without_vector(env):
    cfg, store = env

    async def run():
        r = await commit_memory(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            memory_type="user_preference",
            fact_claim="User prefers dark mode in VS Code with Monokai Pro theme.",
            confidence_score=0.92,
            session_id="s1",
        )
        assert r["status"] == "ok"
        mid = r["memory_id"]

        # Dedup
        r2 = await commit_memory(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            memory_type="user_preference",
            fact_claim="User prefers dark mode in VS Code with Monokai Pro theme.",
            confidence_score=0.92,
        )
        assert r2["deduplicated"] is True

        recall = await recall_context(
            config=cfg,
            store=store,
            embed_provider=None,
            chroma=None,
            user_id="user_001",
            query="IDE theme preferences",
            session_id="s1",
            limit=5,
        )
        assert recall["status"] == "ok"
        assert recall["hit_count"] >= 1
        # Progressive: no full dump key
        assert "hits" in recall
        assert "summary" in recall["hits"][0]

        detail = expand_memory_detail(
            store=store,
            memory_id=mid,
            user_id="user_001",
            config=cfg,
        )
        assert detail["status"] == "ok"
        assert "dark mode" in detail["detail"]

        # Scope isolation
        with pytest.raises(Exception):
            expand_memory_detail(
                store=store,
                memory_id=mid,
                user_id="other_user",
                config=cfg,
            )

    asyncio.run(run())


def test_reject_secret_on_commit(env):
    cfg, store = env

    async def run():
        from strata_memory.governance import ToolError

        with pytest.raises(ToolError) as ei:
            await commit_memory(
                config=cfg,
                store=store,
                embed_provider=None,
                chroma=None,
                user_id="user_001",
                memory_type="factual_truth",
                fact_claim="Production password is hunter2_secret_value_xx",
                confidence_score=0.99,
            )
        assert ei.value.code == "SECRET_DETECTED"

    asyncio.run(run())
