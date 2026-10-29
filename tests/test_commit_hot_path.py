"""commit_memory must not count the chroma or rewrite the stamp when the stamp already matches."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from strata_memory import embedder_stamp
from strata_memory.config import Config, ensure_palace, save_config, truth_db_path
from strata_memory.embedder_stamp import identity_dict, read_stamp, write_stamp
from strata_memory.pipeline import commit as commit_mod
from strata_memory.pipeline.commit import commit_memory
from strata_memory.storage.sqlite_vectors import SqliteVectorStore
from strata_memory.storage.truth_store import TruthStore

IDENT = identity_dict(provider="local", model="hashing", dimension=4, backend="hashing")


class _HashEmbed:
    backend = "hashing"

    async def embed(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


class _CountingChroma(SqliteVectorStore):
    counts = 0

    def count(self) -> int:
        type(self).counts += 1
        return super().count()


def _env(tmp_path: Path):
    palace = tmp_path / "palace"
    ensure_palace(palace)
    cfg = Config(
        palace_path=str(palace),
        mode="personal",
        embedding={"provider": "local", "model": "hashing", "dimension": 4, "mode": "local"},
        cbt={"enabled": False, "mode": "off", "cooling_hours": 48, "detect_distortions": False},
    )
    save_config(cfg)
    _CountingChroma.counts = 0
    return cfg, TruthStore(truth_db_path(palace)), _CountingChroma(palace / "l2_vector")


def _commit(cfg, store, chroma, i: int):
    return asyncio.run(
        commit_memory(
            config=cfg,
            store=store,
            embed_provider=_HashEmbed(),
            chroma=chroma,
            user_id="user_a",
            memory_type="factual_truth",
            fact_claim=f"Service number {i} listens on port {9000 + i} in production.",
            confidence_score=0.95,
        )
    )


def test_matching_stamp_skips_count(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path)
    write_stamp(chroma.persist_dir, IDENT)

    for i in range(5):
        assert _commit(cfg, store, chroma, i)["indexed"] is True

    assert _CountingChroma.counts == 0
    assert chroma.count() == 5


def test_matching_stamp_is_not_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg, store, chroma = _env(tmp_path)
    write_stamp(chroma.persist_dir, IDENT)
    writes: list[dict] = []
    monkeypatch.setattr(commit_mod, "write_stamp", lambda persist, ident: writes.append(ident))

    _commit(cfg, store, chroma, 1)

    assert writes == []


def test_first_commit_on_empty_unstamped_index_stamps_it(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path)
    assert read_stamp(chroma.persist_dir) is None

    assert _commit(cfg, store, chroma, 1)["indexed"] is True

    assert read_stamp(chroma.persist_dir) == IDENT


def test_unstamped_non_empty_index_still_refuses_vectors(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path)
    chroma.add(
        documents=["legacy"], metadatas=[{"memory_id": "legacy"}], ids=["legacy"], embeddings=[[0.4, 0.3, 0.2, 0.1]]
    )

    out = _commit(cfg, store, chroma, 1)

    assert out["indexed"] is False
    assert chroma.count() == 1


def test_stamp_removed_by_another_process_is_noticed(tmp_path: Path):
    cfg, store, chroma = _env(tmp_path)
    write_stamp(chroma.persist_dir, IDENT)
    _commit(cfg, store, chroma, 1)
    # e.g. a rebuild in another process unlinked the stamp before resetting
    embedder_stamp.stamp_path(chroma.persist_dir).unlink()

    out = _commit(cfg, store, chroma, 2)

    assert out["indexed"] is False  # non-empty and unstamped -> refuse, as before
