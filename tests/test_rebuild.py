"""Integration coverage for rebuilding an unstamped, pre-upgrade Chroma index."""

from __future__ import annotations

import asyncio
from pathlib import Path

from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.embedder_stamp import identity_dict, read_stamp, write_stamp
from strata_memory.ops.rebuild import strata_rebuild_index
from strata_memory.storage.chroma import ChromaStore
from strata_memory.storage.truth_store import TruthStore


class _HashEmbed:
    backend = "hashing"

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class _FailingEmbed(_HashEmbed):
    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


def _legacy_index(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        version="2.2.1",
        embedding={"provider": "local", "model": "hashing", "dimension": 4, "mode": "local"},
        cbt={"enabled": False, "mode": "off", "cooling_hours": 48, "detect_distortions": False},
    )
    save_config(cfg)
    store = TruthStore(truth_db_path(palace))
    row = store.insert_memory(
        tenant_id="",
        user_id="user_a",
        session_id="",
        memory_type="factual_truth",
        fact_claim="Legacy memory created before embedder stamps were introduced.",
        content_hash="legacy-memory",
        confidence=0.95,
    )
    chroma = ChromaStore(palace / "l2_vector")
    chroma.add(
        documents=[row["fact_claim"]],
        metadatas=[{"memory_id": row["id"]}],
        ids=[row["id"]],
        embeddings=[[0.1, 0.2, 0.3, 0.4]],
    )
    # This is the main-era state: durable rows and vectors exist, no stamp.
    assert read_stamp(chroma.persist_dir) is None
    return cfg, store, chroma


def test_rebuild_upgrades_legacy_unstamped_index_and_stamps_only_after_success(tmp_path: Path):
    cfg, store, chroma = _legacy_index(tmp_path)

    result = asyncio.run(
        strata_rebuild_index(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            confirm=True,
        )
    )

    assert result["status"] == "ok"
    assert result["indexed"] == 1
    assert result["failed"] == 0
    assert chroma.count() == 1
    assert read_stamp(chroma.persist_dir) == identity_dict(
        provider="local", model="hashing", dimension=4, backend="hashing"
    )


def test_failed_rebuild_returns_error_and_does_not_write_stamp(tmp_path: Path):
    cfg, store, chroma = _legacy_index(tmp_path)
    write_stamp(
        chroma.persist_dir,
        identity_dict(provider="local", model="old-model", dimension=4, backend="hashing"),
    )

    result = asyncio.run(
        strata_rebuild_index(
            config=cfg,
            store=store,
            embed_provider=_FailingEmbed(),
            chroma=chroma,
            confirm=True,
        )
    )

    assert result["status"] == "error"
    assert result["error_code"] == "REBUILD_INCOMPLETE"
    assert result["failed"] == 1
    assert read_stamp(chroma.persist_dir) is None
