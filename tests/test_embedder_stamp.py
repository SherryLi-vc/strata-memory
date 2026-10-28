"""Vector reads and writes refuse a different embedder at the same dimension."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.embedder_stamp import identity_dict, incompatibility, write_stamp
from strata_memory.governance import ToolError
from strata_memory.pipeline.commit import commit_memory
from strata_memory.pipeline.recall import recall_context
from strata_memory.storage.chroma import ChromaStore
from strata_memory.storage.truth_store import TruthStore


class _HashEmbed:
    backend = "hashing"

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def test_unstamped_and_mismatched_indexes_are_rejected(tmp_path: Path):
    persist = tmp_path / "vectors"
    persist.mkdir()
    local = identity_dict(provider="local", model="hashing", dimension=384, backend="hashing")
    assert incompatibility(persist, local, vector_count=0) is None
    assert incompatibility(persist, local, vector_count=2) == "EMBEDDER_UNSTAMPED"
    write_stamp(persist, local)
    assert incompatibility(persist, local, vector_count=2) is None
    other = identity_dict(provider="siliconflow", model="BAAI/bge-m3", dimension=384, backend="http")
    assert incompatibility(persist, other, vector_count=2) == "EMBEDDER_MISMATCH"


def test_recall_fails_when_the_stamp_does_not_match(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.1",
        embedding={"provider": "local", "model": "hashing", "dimension": 384, "mode": "local"},
        cbt={"enabled": False, "mode": "off", "cooling_hours": 48, "detect_distortions": False},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    chroma = ChromaStore(palace / "l2_vector")

    async def setup():
        return await commit_memory(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            user_id="user_a",
            memory_type="factual_truth",
            fact_claim="The API gateway listens on port 8017 in production.",
            confidence_score=0.95,
        )

    created = asyncio.run(setup())
    assert created["indexed"] is True
    write_stamp(
        chroma.persist_dir,
        identity_dict(provider="siliconflow", model="BAAI/bge-m3", dimension=384, backend="http"),
    )

    async def ask():
        return await recall_context(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            user_id="user_a",
            query="API gateway listens on port 8017",
            limit=3,
        )

    with pytest.raises(ToolError) as raised:
        asyncio.run(ask())
    assert raised.value.code == "EMBEDDER_MISMATCH"
